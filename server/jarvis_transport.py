"""Optional pinned SSH transport. Missing/private-disabled settings never start a process."""
import hashlib
import json
import os
import re
import shlex
import stat
import subprocess
import threading
import time
from pathlib import Path


HOST_PATTERN = re.compile(r'[a-z_][a-z0-9_-]{0,31}@[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?')
WORKER = '/opt/data/workspace/libra-mission-control/server/jarvis_runtime.py'
PYTHON = '/opt/hermes/.venv/bin/python'
CONFIG_FIELDS = {'enabled', 'host', 'identity_file', 'container_id', 'remote_worker',
                 'runtime_sha256', 'hermes_fingerprint'}
ISOLATION = {'tools': [], 'memory': False, 'context_files': False, 'soul': False, 'persistence': False}
MAX_RESPONSE_BYTES = 64 * 1024
MAX_PAYLOAD_BYTES = 256 * 1024


class TransportError(Exception):
    """Messages are safe for the application; raw SSH output is never attached."""


class JarvisTransport:
    verify_timeout = 25
    chat_timeout = 55

    def __init__(self, app):
        self.path = Path(app.store.directory) / 'jarvis-connection.json'
        self.lock = threading.RLock()
        self.chat_slots = threading.BoundedSemaphore(2)
        self.cached = None

    def configuration(self):
        """The connection lives in private application storage, never Hermes state or public assets."""
        try:
            info = self.path.lstat()
        except FileNotFoundError:
            return None, None
        except OSError:
            raise TransportError('Private Hermes connection settings are unavailable.')
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600 or info.st_uid != os.getuid():
            raise TransportError('Private Hermes connection settings must be an owner-only regular file with mode 0600.')
        descriptor = None
        try:
            descriptor = os.open(str(self.path), os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
            actual = os.fstat(descriptor)
            if actual.st_ino != info.st_ino or actual.st_dev != info.st_dev or actual.st_uid != os.getuid() or stat.S_IMODE(actual.st_mode) != 0o600 or not stat.S_ISREG(actual.st_mode):
                raise TransportError('Private Hermes connection settings changed while reading.')
            raw = os.read(descriptor, 16385)
            if len(raw) > 16384:
                raise TransportError('Private Hermes connection settings are invalid.')
            value = json.loads(raw.decode('utf-8'))
        except TransportError:
            raise
        except (OSError, ValueError, UnicodeError, RecursionError):
            raise TransportError('Private Hermes connection settings are invalid or unavailable.')
        finally:
            if descriptor is not None:
                os.close(descriptor)
        if not isinstance(value, dict) or set(value) - CONFIG_FIELDS or type(value.get('enabled')) is not bool:
            raise TransportError('Private Hermes connection settings contain unsupported fields.')
        if not value['enabled']:
            return None, None
        if set(value) != CONFIG_FIELDS or not isinstance(value.get('host'), str) or not HOST_PATTERN.fullmatch(value['host']) or value.get('remote_worker') != WORKER:
            raise TransportError('The approved Hermes connection target is not configured correctly.')
        if not isinstance(value['container_id'], str) or not re.fullmatch(r'[0-9a-f]{12,64}', value['container_id']):
            raise TransportError('The approved Hermes container is not configured correctly.')
        for field in ('runtime_sha256', 'hermes_fingerprint'):
            if not isinstance(value[field], str) or not re.fullmatch(r'[0-9a-f]{64}', value[field]):
                raise TransportError('Pinned Hermes runtime verification is not configured.')
        identity = value['identity_file']
        if not isinstance(identity, str) or not Path(identity).is_absolute() or '\x00' in identity or '\n' in identity or '\r' in identity:
            raise TransportError('The approved SSH identity is unavailable.')
        # SSH reads its key itself. The dashboard checks metadata only and never opens key contents.
        try:
            identity_info = Path(identity).stat()
        except (OSError, ValueError):
            raise TransportError('The approved SSH identity is unavailable.')
        if not stat.S_ISREG(identity_info.st_mode) or identity_info.st_uid != os.getuid() or stat.S_IMODE(identity_info.st_mode) & 0o077:
            raise TransportError('The approved SSH identity must be a private owner-only file.')
        return value, hashlib.sha256(raw).hexdigest()

    def command(self, config, mode):
        if mode not in ('--verify', '--chat'):
            raise TransportError('Unsupported Hermes operation.')
        remote = ' '.join(shlex.quote(item) for item in
                          ('sudo', '-n', 'docker', 'exec', '-i', config['container_id'], PYTHON, WORKER, mode))
        return ['ssh', '-T', '-i', config['identity_file'], '-o', 'BatchMode=yes',
                '-o', 'IdentitiesOnly=yes', '-o', 'StrictHostKeyChecking=yes',
                '-o', 'ConnectTimeout=10', '-o', 'ClearAllForwardings=yes', config['host'], remote]

    def invoke(self, config, mode, payload=None):
        try:
            raw = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8') if payload is not None else b''
            if len(raw) > MAX_PAYLOAD_BYTES:
                raise TransportError('This shipment briefing is too large for the isolated connection.')
            result = subprocess.run(self.command(config, mode), input=raw, stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL, timeout=self.verify_timeout if mode == '--verify' else self.chat_timeout,
                                    check=False)
            if result.returncode != 0 or not isinstance(result.stdout, bytes) or len(result.stdout) > MAX_RESPONSE_BYTES:
                raise TransportError('The isolated Hermes connection could not complete this request.')
            response = json.loads(result.stdout.decode('utf-8'))
        except TransportError:
            raise
        except (OSError, subprocess.SubprocessError, ValueError, TypeError, UnicodeError, RecursionError):
            raise TransportError('The isolated Hermes connection could not complete this request.')
        if not isinstance(response, dict) or response.get('ok') is not True:
            raise TransportError('Hermes did not return a verified isolated response.')
        isolation = response.get('isolation')
        if not isinstance(isolation, dict) or set(isolation) != set(ISOLATION) or isolation.get('tools') != [] or type(isolation.get('tools')) is not list or any(isolation.get(key) is not False for key in ISOLATION if key != 'tools'):
            raise TransportError('Hermes shipment-only isolation could not be verified.')
        if response.get('worker_sha256') != config['runtime_sha256'] or response.get('runtime_fingerprint') != config['hermes_fingerprint']:
            raise TransportError('The pinned Hermes runtime changed; verification is required again.')
        return response

    def verified_status(self, config, fingerprint):
        now = time.monotonic()
        if self.cached and self.cached['fingerprint'] == fingerprint and now < self.cached['expires']:
            return dict(self.cached['status'])
        try:
            self.invoke(config, '--verify')
            status = {'enabled': True, 'verified': True, 'reason': 'Pinned shipment-only Hermes runtime verified.'}
        except TransportError as exc:
            status = {'enabled': True, 'verified': False, 'reason': str(exc)}
        self.cached = {'fingerprint': fingerprint, 'status': status,
                       'expires': time.monotonic() + (30 if status['verified'] else 10)}
        return dict(status)

    def status(self):
        with self.lock:
            try:
                config, fingerprint = self.configuration()
            except TransportError as exc:
                self.cached = None
                return {'enabled': False, 'verified': False, 'reason': str(exc)}
            if config is None:
                self.cached = None
                return {'enabled': False, 'verified': False,
                        'reason': 'Hermes shipment-only connection is not enabled; local guidance is active.'}
            return self.verified_status(config, fingerprint)

    def respond(self, message, history, context):
        if not isinstance(message, str) or not message.strip() or len(message) > 2000 or not isinstance(history, list) or len(history) > 12 or not isinstance(context, dict):
            raise TransportError('The shipment conversation is invalid.')
        if any(not isinstance(item, dict) or set(item) != {'role', 'content'} or item['role'] not in ('user', 'assistant') or not isinstance(item['content'], str) or len(item['content']) > 12000 for item in history):
            raise TransportError('The shipment conversation is invalid.')
        with self.lock:
            config, fingerprint = self.configuration()
            if config is None:
                raise TransportError('Hermes shipment-only connection is not enabled.')
            status = self.verified_status(config, fingerprint)
            if not status['verified']:
                raise TransportError(status['reason'])
        if not self.chat_slots.acquire(blocking=False):
            raise TransportError('The isolated Hermes connection is busy; local guidance is available.')
        try:
            payload = {'message': message, 'history': history, 'context': context,
                       'expected_worker_sha256': config['runtime_sha256'],
                       'expected_runtime_fingerprint': config['hermes_fingerprint']}
            response = self.invoke(config, '--chat', payload)
            answer = response.get('text')
            if not isinstance(answer, str) or not answer.strip() or len(answer) > 12000:
                raise TransportError('Hermes did not return a valid shipment briefing.')
            return answer.strip()
        finally:
            self.chat_slots.release()
