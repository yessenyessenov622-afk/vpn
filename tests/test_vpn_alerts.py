import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from app import database, vpn_alerts


class AlertTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'test.sqlite3'
        database.initialize(self.path)
    def tearDown(self): self.tmp.cleanup()
    def report(self, user=101, now=1000):
        with closing(sqlite3.connect(self.path)) as db:
            with db: vpn_alerts.report(db, user, 'revoke', 'controller_error', now)
    def resolve(self, user=101, now=1001):
        with closing(sqlite3.connect(self.path)) as db:
            with db: vpn_alerts.resolve(db, user, now)
    def due(self, now): return vpn_alerts.due(path=self.path, now=now)
    def ack(self, event, now): vpn_alerts.acknowledge(event, path=self.path, now=now)

    def test_first_hourly_repeat_and_recovery_survive_reopen(self):
        self.report()
        first = self.due(1000)[0]
        self.assertEqual(first['phase'], 'failure')
        self.ack(first, 1000)
        self.report(now=1100)
        database.initialize(self.path)
        self.assertEqual(self.due(4599), [])
        self.assertEqual(len(self.due(4600)), 1)
        self.ack(self.due(4600)[0], 4600)
        self.resolve(now=4601)
        resolved = self.due(4601)[0]
        self.assertEqual(resolved['phase'], 'resolved')
        self.ack(resolved, 4601)
        self.assertEqual(self.due(8200), [])

    def test_failed_delivery_remains_due_and_users_are_independent(self):
        self.report(101); self.report(202)
        events = self.due(1000)
        self.assertEqual({e['user_id'] for e in events}, {101, 202})
        self.ack(next(e for e in events if e['user_id'] == 101), 1000)
        self.assertEqual([e['user_id'] for e in self.due(1010)], [202])

    def test_recovery_before_delivery_sends_failure_then_recovery(self):
        self.report(); self.resolve()
        event = self.due(1001)[0]
        self.assertEqual(event['phase'], 'failure')
        self.ack(event, 1001)
        self.assertEqual(self.due(1001)[0]['phase'], 'resolved')

    def test_stale_ack_does_not_hide_new_state(self):
        self.report()
        event = self.due(1000)[0]
        self.resolve()
        self.ack(event, 1001)
        self.assertEqual(self.due(1001)[0]['phase'], 'failure')


if __name__ == '__main__': unittest.main()
