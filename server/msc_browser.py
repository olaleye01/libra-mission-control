"""MSC's public UI through disposable Chromium; stdlib only, no debugging listener."""
import json
import os
import re
from pathlib import Path
import select
import shutil
import subprocess
import sys
import tempfile
import time

URL = 'https://www.msc.com/en/track-a-shipment'


class CollectorError(Exception):
    def __init__(self, message, code='collector_error', phase=None, evidence_text=None, page_title=None):
        super().__init__(message)
        self.code = code
        self.diagnostic = {'code': code}
        if phase:
            self.diagnostic['phase'] = phase
        if page_title:
            self.diagnostic['page_title'] = page_title[:180]
        # Only captured page text, never process stderr or browser credentials.
        self.evidence_text = evidence_text[:131072] if isinstance(evidence_text, str) else None


def challenge_code(state):
    """Generic CAPTCHA disclosures are not challenges; an active verification UI is."""
    if state.get('active_challenge'):
        return 'verification_required'
    title = re.sub(r'\s+', ' ', state.get('title', '')).strip().casefold()
    headings = [re.sub(r'\s+', ' ', h).strip().casefold() for h in state.get('headings', [])]
    if title in ('access denied', 'request rejected', 'forbidden') or any(
            h in ('access denied', 'request rejected', 'forbidden') for h in headings):
        return 'access_denied'
    text = state.get('text', '')
    if 'BILL OF LADING:' in text and 'Tracking results provided by MSC' in text:
        return None
    lower = text.casefold()
    if not state.get('ready') and "you don't have permission to access" in lower:
        return 'access_denied'
    if any(x in lower for x in ('verify you are human', 'verify you are a human',
                               'complete the captcha', 'solve the captcha',
                               'complete the security check', 'unusual traffic')):
        return 'verification_required'
    return None


SNAPSHOT = """JSON.stringify((()=>{
    const visible=e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none';};
    return {url:location.href,title:document.title,text:document.body?document.body.innerText:'',
        ready:!!document.getElementById('trackingNumber'),
        headings:[...document.querySelectorAll('h1,h2,h3')].filter(visible).map(e=>e.innerText),
        active_challenge:[...document.querySelectorAll('iframe[title]')].some(e=>visible(e)&&/challenge/i.test(e.title)&&e.getBoundingClientRect().width>80&&e.getBoundingClientRect().height>80)};
})())"""

# MSC repeats this visible toggle per container. Clicking an open toggle would hide its history.
EXPAND_CONTAINERS = """(()=>{
    const closed=[...document.querySelectorAll('.msc-flow-tracking__more-button')].filter(button=>{
        return !button.disabled&&[...button.querySelectorAll('.msc-icon-plus')].some(plus=>
            getComputedStyle(plus).display!=='none'&&plus.getClientRects().length>0);
    });
    if(closed.length>200)return -1;
    closed.forEach(button=>button.click());
    return closed.length;
})()"""


def browser_path():
    configured = os.environ.get('LIBRA_CHROME_PATH')
    candidates = [configured] if configured else [
        '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
        shutil.which('chromium'), shutil.which('chromium-browser'), shutil.which('google-chrome')]
    for value in candidates:
        if value and Path(value).is_absolute() and Path(value).is_file() and os.access(value, os.X_OK):
            return str(Path(value).resolve())
    return None


class Browser:
    def __enter__(self):
        executable = browser_path()
        if not executable:
            raise CollectorError('Chrome/Chromium is unavailable. Configure LIBRA_CHROME_PATH on the server.', code='browser_unavailable', phase='startup')
        self.profile = tempfile.TemporaryDirectory(prefix='libra-msc-')
        child_read, self.write_fd = os.pipe()
        self.read_fd, child_write = os.pipe()
        self.buffer, self.counter = b'', 0
        self.stderr = tempfile.TemporaryFile()
        self.deadline = time.monotonic()+85
        try:
            self.process = subprocess.Popen([sys.executable, str(Path(__file__).with_name('browser_process.py')),
                executable, str(child_read), str(child_write), self.profile.name],
                pass_fds=(child_read, child_write), stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=self.stderr)
        except OSError:
            self.__exit__(None, None, None)
            raise CollectorError('The isolated browser could not start.', code='browser_start_failed', phase='startup')
        finally:
            os.close(child_read)
            os.close(child_write)
        return self

    def __exit__(self, *args):
        process = getattr(self, 'process', None)
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        for name in ('write_fd', 'read_fd'):
            fd = getattr(self, name, None)
            if fd is not None:
                os.close(fd)
        if getattr(self, 'profile', None):
            self.profile.cleanup()
        if getattr(self, 'stderr', None):
            self.stderr.close()

    def call(self, method, params=None, session=None):
        self.counter += 1
        message = {'id': self.counter, 'method': method, 'params': params or {}}
        if session:
            message['sessionId'] = session
        try:
            os.write(self.write_fd, json.dumps(message).encode()+b'\0')
            while time.monotonic() < self.deadline:
                if b'\0' not in self.buffer:
                    if not select.select([self.read_fd], [], [], min(2, max(0, self.deadline-time.monotonic())))[0]:
                        if self.process.poll() is not None:
                            raise CollectorError('The isolated browser exited. Check its runtime/sandbox configuration.', code='browser_exited', phase='transport')
                        continue
                    chunk = os.read(self.read_fd, 65536)
                    if not chunk:
                        raise CollectorError('The isolated browser closed before returning tracking results.', code='browser_closed', phase='transport')
                    self.buffer += chunk
                    if len(self.buffer) > 4*1024*1024:
                        raise CollectorError('Browser response exceeded the safe size limit.', code='response_limit', phase='transport')
                    continue
                raw, self.buffer = self.buffer.split(b'\0', 1)
                result = json.loads(raw)
                if result.get('id') == self.counter:
                    if 'error' in result:
                        raise CollectorError('Browser protocol failed while reading the tracking page.', code='protocol_error', phase='transport')
                    return result.get('result', {})
        except (OSError, ValueError):
            raise CollectorError('Could not communicate with the isolated browser.', code='transport_error', phase='transport')
        raise CollectorError('MSC lookup timed out. Retry later; previous evidence is retained.', code='timeout', phase='transport')

    def evaluate(self, expression, session):
        reply = self.call('Runtime.evaluate', {'expression': expression, 'returnByValue': True}, session)
        if reply.get('exceptionDetails'):
            raise CollectorError('MSC page structure changed; the collector needs review.', code='page_layout', phase='page')
        return reply.get('result', {}).get('value')


def collect(bl):
    # The only external destination and the script are fixed; BL is JSON data, never code.
    with Browser() as browser:
        target = browser.call('Target.createTarget', {'url': 'about:blank'})['targetId']
        session = browser.call('Target.attachToTarget', {'targetId': target, 'flatten': True})['sessionId']
        browser.call('Page.navigate', {'url': URL}, session)
        submitted = False
        expansion_attempts = 0
        while time.monotonic() < browser.deadline:
            snapshot = browser.evaluate(SNAPSHOT, session)
            state = json.loads(snapshot or '{}')
            text = state.get('text', '')
            if state.get('url', '').split('?')[0].rstrip('/') != URL:
                if state.get('url', '') not in ('about:blank', ''):
                    raise CollectorError('MSC redirected the browser away from the approved tracking page.', code='unexpected_redirect', phase='navigation', evidence_text=text, page_title=state.get('title'))
            blocked = challenge_code(state)
            if blocked:
                message = ('MSC denied access to this tracking browser.' if blocked == 'access_denied' else
                           'MSC requires interactive verification for this tracking browser.')
                raise CollectorError(message+' No bypass was attempted.', code=blocked,
                                     phase='results' if submitted else 'navigation',
                                     evidence_text=text, page_title=state.get('title'))
            if submitted and 'BILL OF LADING:' in text and 'Tracking results provided by MSC' in text:
                expanded = browser.evaluate(EXPAND_CONTAINERS, session)
                if expanded == -1:
                    raise CollectorError('MSC returned too many collapsed container sections for this collector.',
                                         code='response_limit', phase='container_expansion', evidence_text=text,
                                         page_title=state.get('title'))
                if expanded:
                    expansion_attempts += 1
                    if expansion_attempts > 3:
                        raise CollectorError('MSC container histories did not expand after their visible toggles were clicked.',
                                             code='page_layout', phase='container_expansion', evidence_text=text,
                                             page_title=state.get('title'))
                    # Let MSC render the opened sections, then capture only the newly visible text.
                    time.sleep(1)
                    continue
                return text
            if submitted and any(x in text.lower() for x in ('no results found', 'no tracking information', 'no records found')):
                raise CollectorError('MSC did not return tracking records for this BL.', code='not_found', phase='results', evidence_text=text, page_title=state.get('title'))
            if state.get('ready') and not submitted:
                browser.evaluate("""(()=>{
                    document.getElementById('onetrust-reject-all-handler')?.click();
                    const input=document.getElementById('trackingNumber');
                    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input,"""+json.dumps(bl)+""");
                    input.dispatchEvent(new Event('input',{bubbles:true}));
                    input.dispatchEvent(new Event('change',{bubbles:true}));
                    return true;
                })()""", session)
                # Alpine applies the input update in its next microtask.
                browser.evaluate("document.querySelector('.msc-search-autocomplete__search').click()", session)
                submitted = True
            time.sleep(1)
        raise CollectorError('MSC lookup timed out; no shipment facts were changed.', code='timeout', phase='results' if submitted else 'navigation')
