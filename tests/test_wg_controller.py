import base64
import importlib.util
import json
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest.mock import patch


def make_key(n):
    return base64.b64encode(bytes([n]) * 32).decode()


spec = importlib.util.spec_from_file_location('wg_helper', Path(__file__).resolve().parent.parent / 'deploy' / 'wg_controller.py')
helper = importlib.util.module_from_spec(spec)
with patch.dict(sys.modules, {'fcntl': types.SimpleNamespace()}):
    spec.loader.exec_module(helper)


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.config = root / 'wg0.conf'
        self.state = root / 'state'
        self.state.mkdir()
        self.endpoint = root / 'endpoint'
        self.endpoint.write_text('192.0.2.1')
        self.android = make_key(9)
        self.config.write_text('[Interface]\nPrivateKey = hidden\n\n[Peer]\nPublicKey = ' + self.android + '\nAllowedIPs = 10.77.0.2/32\n')
        self.peers = {self.android: '10.77.0.2/32'}
        self.fail_after_set = False
        self.patches = [patch.object(helper, 'CONFIG', self.config), patch.object(helper, 'STATE', self.state),
                        patch.object(helper, 'ENDPOINT', self.endpoint), patch.object(helper, 'wg', self.wg),
                        patch.object(helper, 'atomic_write', lambda path, data, mode: path.write_text(data, encoding='utf-8'))]
        for p in self.patches: p.start()

    def tearDown(self):
        for p in reversed(self.patches): p.stop()
        self.tmp.cleanup()

    def wg(self, *args):
        if args == ('show', 'wg0', 'allowed-ips'):
            return '\n'.join(k + '\t' + v for k, v in self.peers.items())
        if args == ('show', 'wg0', 'public-key'): return make_key(8)
        if args == ('show', 'wg0', 'listen-port'): return '51820'
        if args[:3] == ('set', 'wg0', 'peer'):
            if args[4] == 'remove':
                self.peers.pop(args[3], None)
            else:
                self.peers[args[3]] = args[5]
            if self.fail_after_set: raise TimeoutError()
            return ''
        raise AssertionError(args)

    def add(self, k=None, ip='10.77.0.3/32', expiry=None):
        return helper.execute({'operation': 'add', 'key': k or make_key(1), 'address': ip,
                               'expires_at': int(time.time()) + 100 if expiry is None else expiry})

    def test_add_repeat_and_restart_preserve_android(self):
        self.assertEqual(self.add(), {'confirmed': True})
        self.assertEqual(self.add(), {'confirmed': True})
        saved = helper.configured_peers(self.config.read_text())
        self.assertEqual(saved, self.peers)
        self.peers = dict(saved)  # simulate wg-quick loading the configuration
        self.assertEqual(helper.execute({'operation': 'list'})['peers'][self.android], '10.77.0.2/32')
        self.assertEqual(self.config.read_text().count('PublicKey = ' + make_key(1)), 1)

    def test_conflicts_and_expiry_are_rejected(self):
        self.add()
        for k, ip, expiry in [(make_key(2), '10.77.0.3/32', None), (make_key(1), '10.77.0.4/32', None),
                               (make_key(2), '10.77.0.2/32', None), (make_key(2), '10.77.0.4/32', 1)]:
            with self.assertRaises(Exception): self.add(k, ip, expiry)
        self.assertEqual(len(self.peers), 2)

    def test_unknown_result_is_reconciled_without_duplicate(self):
        self.fail_after_set = True
        with self.assertRaises(TimeoutError): self.add()
        self.assertTrue((self.state / 'pending.json').exists())
        self.fail_after_set = False
        self.assertEqual(self.add(), {'confirmed': True})
        self.assertFalse((self.state / 'pending.json').exists())
        self.assertEqual(self.peers, helper.configured_peers(self.config.read_text()))

    def test_unexplained_mismatch_fails_closed(self):
        self.peers[make_key(2)] = '10.77.0.4/32'
        with self.assertRaises(ValueError): helper.execute({'operation': 'list'})

    def test_remove_is_owned_only_and_survives_restart(self):
        self.add()
        request = {'operation': 'remove', 'key': make_key(1), 'address': '10.77.0.3/32'}
        self.assertEqual(helper.execute(request), {'confirmed': True})
        self.assertEqual(helper.execute(request), {'confirmed': True})
        self.peers = helper.configured_peers(self.config.read_text())
        self.assertNotIn(make_key(1), self.peers)
        self.assertEqual(self.peers[self.android], '10.77.0.2/32')
        with self.assertRaises(Exception):
            helper.execute({'operation': 'remove', 'key': self.android, 'address': '10.77.0.2/32'})

    def test_interrupted_remove_is_reconciled(self):
        self.add()
        self.fail_after_set = True
        req = {'operation': 'remove', 'key': make_key(1), 'address': '10.77.0.3/32'}
        with self.assertRaises(TimeoutError): helper.execute(req)
        self.fail_after_set = False
        self.assertEqual(helper.execute(req), {'confirmed': True})
        self.assertNotIn(make_key(1), self.peers)

    def test_rejects_arbitrary_operations_and_invalid_input(self):
        for request in ({'operation': 'shell', 'command': 'x'}, {'operation': 'add', 'key': 'bad', 'address': '10.77.0.3/32', 'expires_at': 9999999999}, {'operation': 'list', 'key': make_key(1)}):
            with self.assertRaises(Exception): helper.execute(request)


if __name__ == '__main__':
    unittest.main()
