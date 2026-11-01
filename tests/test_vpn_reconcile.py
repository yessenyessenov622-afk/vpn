import base64
import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from app import database, vpn_reconcile, vpn_alerts


def key(n):
    return base64.b64encode(bytes([n]) * 32).decode()


class Controller:
    def __init__(self):
        self.managed = {key(1): '10.77.0.3/32'}
        self.peers = {key(9): '10.77.0.2/32', key(1): '10.77.0.3/32'}
        self.fail = False
    def is_owned(self, k, a): return self.managed.get(k) == a
    def list_peers(self):
        if self.fail: raise TimeoutError()
        return dict(self.peers)
    def remove_if_owned(self, k, a):
        if self.fail: raise TimeoutError()
        self.peers.pop(k, None)
        return True
    def add_if_free(self, k, a, expiry):
        if self.fail: raise TimeoutError()
        if a in self.peers.values(): return False
        self.peers[k] = a
        return True


class ReconcileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / 'users.sqlite3'
        database.initialize(self.db)
        database.register_user(101, self.db)
        database.grant_subscription(101, 1, self.db, now=1000)
        with closing(sqlite3.connect(self.db)) as c:
            with c:
                c.execute("INSERT INTO vpn_devices(user_id,public_key,created_at,updated_at,vpn_ip,server_id,access_state) VALUES(101,?,1000,1000,'10.77.0.3/32','primary','allowed')", (key(1),))
        self.controller = Controller()
    def tearDown(self): self.temp.cleanup()
    def run_at(self, now): return vpn_reconcile.reconcile_one(101, self.controller, path=self.db, clock=lambda: now)
    def state(self):
        with closing(sqlite3.connect(self.db)) as c: return c.execute('SELECT access_state,last_error FROM vpn_devices WHERE user_id=101').fetchone()
    def test_active_expiry_repeat_and_renewal(self):
        self.assertEqual(self.run_at(1001), 'allowed')
        self.assertEqual(self.run_at(87400), 'revoked')
        self.assertEqual(self.run_at(87401), 'revoked')
        self.assertEqual(self.controller.peers[key(9)], '10.77.0.2/32')
        database.grant_subscription(101, 1, self.db, now=87402)
        self.assertEqual(self.run_at(87403), 'allowed')
        self.assertEqual(self.controller.peers[key(1)], '10.77.0.3/32')
    def test_failure_preserves_state_and_retries(self):
        self.controller.fail = True
        self.assertEqual(self.run_at(87400), 'error')
        self.assertEqual(self.state(), ('allowed', 'confirmation_lost'))
        alert = vpn_alerts.due(path=self.db, now=87400)[0]
        self.assertEqual((alert['action'], alert['code'], alert['phase']), ('revoke', 'controller_error', 'failure'))
        vpn_alerts.acknowledge(alert, path=self.db, now=87400)
        self.controller.fail = False
        self.assertEqual(self.run_at(87401), 'revoked')
        self.assertEqual(self.state(), ('revoked', None))
        self.assertEqual(vpn_alerts.due(path=self.db, now=87401)[0]['phase'], 'resolved')
    def test_conflict_and_unowned_are_not_changed(self):
        self.controller.managed.clear()
        self.assertEqual(self.run_at(87400), 'error')
        self.assertIn(key(1), self.controller.peers)
        self.controller.managed[key(1)] = '10.77.0.3/32'
        self.controller.peers[key(2)] = '10.77.0.3/32'
        self.assertEqual(self.run_at(87400), 'error')
        self.assertIn(key(1), self.controller.peers)

    def test_renewal_waits_for_reconciliation_lock(self):
        entered, release = threading.Event(), threading.Event()
        original = self.controller.remove_if_owned
        def slow_remove(k, a):
            entered.set()
            if not release.wait(5): raise TimeoutError()
            return original(k, a)
        self.controller.remove_if_owned = slow_remove
        with ThreadPoolExecutor(max_workers=2) as pool:
            reconciliation = pool.submit(self.run_at, 87400)
            self.assertTrue(entered.wait(5))
            renewal = pool.submit(database.grant_subscription, 101, 1, self.db, now=87401)
            self.assertFalse(renewal.done())
            release.set()
            self.assertEqual(reconciliation.result(timeout=5), 'revoked')
            self.assertIsNotNone(renewal.result(timeout=5))
        self.assertEqual(self.run_at(87402), 'allowed')


if __name__ == '__main__': unittest.main()
