"""No-network checks for challenge diagnosis and destination discovery."""
import json
import shutil
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'server'))
from msc_browser import URL, CollectorError, challenge_code, collect, SNAPSHOT, EXPAND_CONTAINERS
from msc_tracking import parse, discover_destination
from test_tracking import page


class ChallengeDiagnosisTests(unittest.TestCase):
    def test_generic_captcha_disclosures_do_not_report_a_block(self):
        form = dict(url=URL, title='MSC shipment tracking', ready=True,
                    text='Tracking\nThis site is protected by reCAPTCHA.', headings=['Tracking'])
        self.assertIsNone(challenge_code(form))
        form['text'] = page()+'\nCAPTCHA helps prevent unusual traffic.'
        self.assertIsNone(challenge_code(form))

    def test_active_challenge_and_denial_are_different_codes(self):
        self.assertEqual(challenge_code(dict(title='Access Denied',text='Denied',headings=[])), 'access_denied')
        self.assertEqual(challenge_code(dict(title='Tracking',text='Verify you are human',headings=[])), 'verification_required')
        self.assertEqual(challenge_code(dict(title='Tracking',text=page(),headings=[],active_challenge=True)), 'verification_required')

    def test_coded_diagnostics_are_bounded_and_not_browser_stderr(self):
        exc = CollectorError('MSC denied access.',code='access_denied',phase='navigation',
                             page_title='a'*300,evidence_text='b'*200000)
        self.assertEqual(exc.code,'access_denied')
        self.assertEqual(exc.diagnostic['phase'],'navigation')
        self.assertEqual(len(exc.diagnostic['page_title']),180)
        self.assertEqual(len(exc.evidence_text),131072)
        self.assertNotIn('stderr',exc.diagnostic)

    def test_collect_stops_on_confirmed_denial_and_keeps_diagnostic(self):
        class FakeBrowser:
            deadline=time.monotonic()+100
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def call(self,method,params=None,session=None):
                return {'targetId':'test-target'} if method=='Target.createTarget' else {'sessionId':'test-session'}
            def evaluate(self,expression,session):
                return json.dumps(dict(url=URL,title='Access Denied',text="You don't have permission to access this resource.",headings=['Access Denied']))
        with patch('msc_browser.Browser',FakeBrowser):
            with self.assertRaises(CollectorError) as raised:collect('MSCDEMO12345')
        self.assertEqual(raised.exception.code,'access_denied')
        self.assertEqual(raised.exception.diagnostic['phase'],'navigation')
        self.assertIn("don't have permission",raised.exception.evidence_text)

    def test_collect_can_finish_with_generic_captcha_footer(self):
        class FakeBrowser:
            deadline=time.monotonic()+100
            snapshots=0
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def call(self,method,params=None,session=None):
                return {'targetId':'test-target'} if method=='Target.createTarget' else {'sessionId':'test-session'}
            def evaluate(self,expression,session):
                if expression==EXPAND_CONTAINERS:return 0
                if expression!=SNAPSHOT:return True
                self.snapshots+=1
                text='Tracking\nThis site is protected by reCAPTCHA.' if self.snapshots==1 else page()+'\nThis site is protected by reCAPTCHA.'
                return json.dumps(dict(url=URL,title='Tracking',text=text,ready=True,headings=['Tracking']))
        with patch('msc_browser.Browser',FakeBrowser),patch('msc_browser.time.sleep'):
            self.assertIn('BILL OF LADING:',collect('MSCDEMO12345'))

    def test_collect_reads_visible_text_again_after_expanding_containers(self):
        class FakeBrowser:
            deadline=time.monotonic()+100
            snapshots=0
            expansions=0
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def call(self,method,params=None,session=None):
                return {'targetId':'test-target'} if method=='Target.createTarget' else {'sessionId':'test-session'}
            def evaluate(self,expression,session):
                if expression==EXPAND_CONTAINERS:
                    self.expansions+=1
                    return 1 if self.expansions==1 else 0
                if expression!=SNAPSHOT:return True
                self.snapshots+=1
                if self.snapshots==1:text='Tracking'
                elif self.snapshots==2:text=page()+'\nOne other container is collapsed.'
                else:text=page(containers=('ABCD1234567','EFGH7654321'))
                return json.dumps(dict(url=URL,title='Tracking',text=text,ready=True,headings=['Tracking']))
        browser=FakeBrowser()
        with patch('msc_browser.Browser',return_value=browser),patch('msc_browser.time.sleep'):
            captured=collect('MSCDEMO12345')
        self.assertIn('EFGH7654321',captured)
        self.assertEqual(browser.expansions,2)
        self.assertEqual(browser.snapshots,3)

    def test_visible_toggle_script_selects_closed_enabled_sections_only(self):
        executable=shutil.which('node')
        if not executable:self.skipTest('Node is unavailable for the DOM-script unit harness')
        # Execute the actual script against a small DOM double; no browser or network is involved.
        harness="""const vm=require('vm'),clicks=[];
        const icon=(display,rects)=>({display,getClientRects:()=>Array(rects).fill({})});
        const button=(id,disabled,icons)=>({disabled,
            querySelectorAll:()=>icons,
            click:()=>clicks.push(id)});
        const buttons=[button('open',false,[icon('none',0),icon('none',0)]),
            button('closed',false,[icon('none',0),icon('inline',1)]),
            button('disabled',true,[icon('inline',1)]),button('hidden',false,[icon('inline',0)]),button('missing',false,[])];
        const result=vm.runInNewContext(process.argv[1],{
            document:{querySelectorAll:()=>buttons},getComputedStyle:e=>({display:e.display})});
        process.stdout.write(JSON.stringify({result,clicks}));"""
        completed=subprocess.run([executable,'-e',harness,EXPAND_CONTAINERS],capture_output=True,text=True,timeout=10,check=True)
        self.assertEqual(json.loads(completed.stdout),{'result':1,'clicks':['closed']})


class DestinationDiscoveryTests(unittest.TestCase):
    def test_explicit_header_discovers_destination_without_setup(self):
        result=parse(page(),'MSCDEMO12345',None,'2026-10-31')
        self.assertEqual(result['destination'],'Apapa, NG')
        self.assertEqual(result['milestones']['discharge'],'2024-06-04')
        self.assertEqual(discover_destination(page()),'Apapa, NG')

    def test_country_and_known_port_remain_required(self):
        for port in ('Singapore, SG','Unreviewed New Port, NG'):
            with self.subTest(port=port):
                with self.assertRaises(CollectorError) as raised:parse(page(port=port),'MSCDEMO12345',None,'2026-10-31')
                self.assertEqual(raised.exception.code,'destination_unsupported')

    def test_an_explicit_mismatch_remains_invalid(self):
        with self.assertRaises(CollectorError):parse(page(),'MSCDEMO12345','Onne, NG','2026-10-31')
