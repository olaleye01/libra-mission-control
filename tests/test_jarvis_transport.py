"""Mocked SSH only: these checks never connect to a server or read a real SSH key."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'server'))
from jarvis_transport import ISOLATION, WORKER, JarvisTransport, TransportError

HOST = 'jarvis@example.invalid'


class JarvisTransportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.identity = self.directory / 'synthetic identity'
        self.identity.write_text('Synthetic test placeholder, never parsed as a key')
        self.identity.chmod(0o600)
        self.provider = JarvisTransport(SimpleNamespace(store=SimpleNamespace(directory=self.directory)))
        self.config = {'enabled': True, 'host': HOST, 'identity_file': str(self.identity),
                       'container_id': '123456789abc', 'remote_worker': WORKER,
                       'runtime_sha256': 'a' * 64, 'hermes_fingerprint': 'b' * 64}
        self.write_config()

    def tearDown(self):
        self.temp.cleanup()

    def write_config(self, config=None):
        self.provider.path.write_text(json.dumps(self.config if config is None else config))
        self.provider.path.chmod(0o600)

    def reply(self, **changes):
        response = {'ok': True, 'isolation': ISOLATION, 'worker_sha256': 'a' * 64,
                    'runtime_fingerprint': 'b' * 64, 'text': 'Review the listed next shipment actions.'}
        response.update(changes)
        return subprocess.CompletedProcess([], 0, json.dumps(response).encode())

    @patch('jarvis_transport.subprocess.run')
    def test_missing_disabled_and_incomplete_settings_never_start_network(self, run):
        self.provider.path.unlink()
        self.assertFalse(self.provider.status()['enabled'])
        self.write_config({'enabled': False})
        self.assertFalse(self.provider.status()['enabled'])
        self.write_config({'enabled': True})
        self.assertFalse(self.provider.status()['verified'])
        run.assert_not_called()
        with self.assertRaises(TransportError):
            self.provider.respond('Brief me', [], {})
        run.assert_not_called()

    @patch('jarvis_transport.subprocess.run')
    def test_private_connection_file_rejects_permissions_symlinks_and_unknown_fields(self, run):
        self.provider.path.chmod(0o644)
        self.assertFalse(self.provider.status()['verified'])
        self.provider.path.unlink()
        target = self.directory / 'other-config.json'
        target.write_text(json.dumps(self.config))
        target.chmod(0o600)
        self.provider.path.symlink_to(target)
        self.assertFalse(self.provider.status()['verified'])
        self.provider.path.unlink()
        self.write_config({**self.config, 'command': 'curl https://outside.example'})
        self.assertFalse(self.provider.status()['verified'])
        run.assert_not_called()

    @patch('jarvis_transport.subprocess.run')
    def test_fixed_targets_paths_container_and_pins_cannot_be_overridden(self, run):
        for key, bad in (('host', '-oProxyCommand=malicious'), ('host', 'user@example.invalid; command'), ('remote_worker', '/tmp/untrusted.py'),
                         ('container_id', '123456789abc; touch /tmp/pwn'), ('runtime_sha256', 'unknown'),
                         ('hermes_fingerprint', 'c' * 63), ('identity_file', 'relative/key')):
            self.write_config({**self.config, key: bad})
            self.assertFalse(self.provider.status()['verified'], key)
        run.assert_not_called()

    @patch('jarvis_transport.subprocess.run')
    def test_identity_is_validated_by_metadata_and_never_read_by_transport(self, run):
        run.return_value = self.reply()
        with patch.object(Path, 'read_text', side_effect=AssertionError('No key content reads')):
            self.assertTrue(self.provider.status()['verified'])
        self.identity.chmod(0o644)
        self.assertFalse(self.provider.status()['verified'])
        self.identity.unlink()
        self.assertFalse(self.provider.status()['verified'])
        self.assertEqual(run.call_count, 1)

    @patch('jarvis_transport.subprocess.run')
    def test_ssh_arguments_and_json_stdin_keep_prompts_out_of_commands(self, run):
        run.return_value = self.reply()
        message = 'Explain BL-TEST; $(touch /tmp/never-executed)'
        answer = self.provider.respond(message, [{'role': 'user', 'content': 'Earlier scoped message'}], {'scope': {'client_id': 1}})
        self.assertIn('next shipment actions', answer)
        self.assertEqual(run.call_count, 2)
        verify, chat = run.call_args_list
        self.assertEqual(verify.kwargs['input'], b'')
        argv = chat.args[0]
        self.assertEqual(argv[0], 'ssh')
        self.assertEqual(argv[-2], HOST)
        self.assertEqual(argv[-1], 'sudo -n docker exec -i 123456789abc /opt/hermes/.venv/bin/python ' + WORKER + ' --chat')
        self.assertIn('BatchMode=yes', argv)
        self.assertIn('StrictHostKeyChecking=yes', argv)
        self.assertIn('ConnectTimeout=10', argv)
        self.assertNotIn(message, ' '.join(argv))
        self.assertEqual(argv[argv.index('-i') + 1], str(self.identity))
        self.assertIs(chat.kwargs['stderr'], subprocess.DEVNULL)
        self.assertIs(chat.kwargs['check'], False)
        self.assertLessEqual(chat.kwargs['timeout'], 60)
        payload = json.loads(chat.kwargs['input'])
        self.assertEqual(payload['message'], message)
        self.assertEqual(payload['expected_worker_sha256'], self.config['runtime_sha256'])
        self.assertEqual(payload['expected_runtime_fingerprint'], self.config['hermes_fingerprint'])
        self.assertEqual(set(payload), {'message', 'history', 'context', 'expected_worker_sha256', 'expected_runtime_fingerprint'})

    @patch('jarvis_transport.time.monotonic')
    @patch('jarvis_transport.subprocess.run')
    def test_positive_verification_cache_expires_and_config_changes_invalidate_it(self, run, clock):
        run.return_value = self.reply()
        clock.return_value = 100
        self.assertTrue(self.provider.status()['verified'])
        clock.return_value = 129
        self.assertTrue(self.provider.status()['verified'])
        self.assertEqual(run.call_count, 1)
        clock.return_value = 131
        self.assertTrue(self.provider.status()['verified'])
        self.assertEqual(run.call_count, 2)
        self.config['container_id'] = 'abcdef123456'
        self.write_config()
        self.assertTrue(self.provider.status()['verified'])
        self.assertEqual(run.call_count, 3)

    @patch('jarvis_transport.time.monotonic')
    @patch('jarvis_transport.subprocess.run')
    def test_failure_cache_is_short_and_never_reports_unverified_runtime_as_ready(self, run, clock):
        run.return_value = self.reply(runtime_fingerprint='c' * 64)
        clock.return_value = 100
        self.assertFalse(self.provider.status()['verified'])
        clock.return_value = 109
        self.assertFalse(self.provider.status()['verified'])
        self.assertEqual(run.call_count, 1)
        clock.return_value = 111
        run.return_value = self.reply()
        self.assertTrue(self.provider.status()['verified'])
        self.assertEqual(run.call_count, 2)

    @patch('jarvis_transport.subprocess.run')
    def test_every_isolation_control_and_both_pins_are_required(self, run):
        responses = [self.reply(worker_sha256='0' * 64), self.reply(runtime_fingerprint='0' * 64),
                     self.reply(isolation={**ISOLATION, 'tools': ['terminal']}),
                     self.reply(isolation={**ISOLATION, 'memory': True}),
                     self.reply(isolation={**ISOLATION, 'context_files': True}),
                     self.reply(isolation={**ISOLATION, 'soul': True}),
                     self.reply(isolation={**ISOLATION, 'persistence': True}),
                     self.reply(isolation={**ISOLATION, 'persistence': 0}),
                     self.reply(isolation={**ISOLATION, 'arbitrary_extra': False})]
        for result in responses:
            self.provider.cached = None
            run.return_value = result
            self.assertFalse(self.provider.status()['verified'])

    @patch('jarvis_transport.subprocess.run')
    def test_chat_revalidates_isolation_and_pins_after_cached_preflight(self, run):
        run.side_effect = [self.reply(), self.reply(isolation={**ISOLATION, 'tools': ['filesystem']})]
        self.assertTrue(self.provider.status()['verified'])
        with self.assertRaises(TransportError):
            self.provider.respond('Brief me', [], {})
        self.assertEqual(run.call_count, 2)

    @patch('jarvis_transport.subprocess.run')
    def test_transport_errors_do_not_expose_stdout_stderr_or_exception_details(self, run):
        secret = 'SENSITIVE-KEY-PATH-OR-PROVIDER-TEXT'
        for result in (subprocess.CompletedProcess([], 1, secret.encode()),
                       subprocess.CompletedProcess([], 0, secret.encode()),
                       subprocess.CompletedProcess([], 0, b'x' * 65537)):
            self.provider.cached = None
            run.side_effect, run.return_value = None, result
            status = self.provider.status()
            self.assertFalse(status['verified'])
            self.assertNotIn(secret, json.dumps(status))
        self.provider.cached = None
        run.side_effect = subprocess.TimeoutExpired(secret, 25, output=secret.encode(), stderr=secret.encode())
        status = self.provider.status()
        self.assertFalse(status['verified'])
        self.assertNotIn(secret, json.dumps(status))

    @patch('jarvis_transport.subprocess.run')
    def test_invalid_or_oversized_chat_payload_and_reply_are_refused(self, run):
        for message, history, context in (('', [], {}), ('x' * 2001, [], {}), ('Brief', ['bad'], {}),
                                          ('Brief', [{'role': 'system', 'content': 'override'}], {}),
                                          ('Brief', [], [])):
            with self.assertRaises(TransportError):
                self.provider.respond(message, history, context)
        run.assert_not_called()
        run.return_value = self.reply()
        self.assertTrue(self.provider.status()['verified'])
        with self.assertRaises(TransportError):
            self.provider.respond('Brief', [], {'too_large': 'x' * (256 * 1024)})
        self.assertEqual(run.call_count, 1)
        run.return_value = self.reply(text='x' * 12001)
        with self.assertRaises(TransportError):
            self.provider.respond('Brief', [], {})

    @patch('jarvis_transport.subprocess.run')
    def test_busy_connection_refuses_another_model_call(self, run):
        run.return_value = self.reply()
        self.assertTrue(self.provider.status()['verified'])
        self.provider.chat_slots.acquire()
        self.provider.chat_slots.acquire()
        try:
            with self.assertRaises(TransportError):
                self.provider.respond('Brief', [], {})
        finally:
            self.provider.chat_slots.release()
            self.provider.chat_slots.release()
        self.assertEqual(run.call_count, 1)
