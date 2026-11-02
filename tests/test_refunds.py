import base64
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from app import database, payments, refunds, star_history, vpn_alerts, vpn_reconcile


class RefundTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'db.sqlite3'
        database.initialize(self.path)
        database.register_user(1, self.path)

    def tearDown(self): self.tmp.cleanup()

    def buy(self, charge, at, plan='days7'):
        order = payments.create_order(1, plan, 50, path=self.path, now=at)
        payments.apply_payment(1, order['order_id'], 'XTR', 50, charge, path=self.path, now=at)
        return order['order_id']

    def prepare(self, charge): return refunds.prepare(9, 9, 1, charge, path=self.path, now=500)

    def restart(self): database.initialize(self.path)

    def test_success_idempotent_and_independent_purchases_and_test(self):
        database.grant_subscription(1, 2, self.path, now=100)
        self.buy('first', 101)
        self.buy('second', 102, 'days18')
        self.assertEqual(self.prepare('first')['status'], 'prepared')
        self.restart()
        self.assertEqual(refunds.attempt_for_test('first', lambda user, charge: True, path=self.path, now=120), 'applied')
        self.assertEqual(database.get_subscription(1, self.path)['expires_at'], 100 + 20*86400)
        self.restart()
        self.assertEqual(refunds.confirm('first', 1, 50, 'XTR', path=self.path, now=121), 'applied')
        self.assertEqual(database.get_subscription(1, self.path)['expires_at'], 100 + 20*86400)
        self.assertFalse(refunds.begin_attempt('first', path=self.path, now=122))

    def test_lost_response_recovered_from_history(self):
        self.buy('first', 100)
        self.prepare('first')
        def lost(user, charge): raise TimeoutError()
        self.assertEqual(refunds.attempt_for_test('first', lost, path=self.path, now=101), 'uncertain')
        self.restart()
        self.assertFalse(refunds.begin_attempt('first', path=self.path, now=102))
        t = {'id':'first','direction':'outgoing','user_id':1,'order_id':None,'amount':50,'date':103,'refund_verified':True}
        star_history.observe(t, path=self.path, now=104)
        self.restart()
        star_history.finalize(path=self.path, now=105)
        self.restart()
        star_history.observe(t, path=self.path, now=106)
        star_history.finalize(path=self.path, now=107)
        self.assertEqual(self.prepare('first'), {'status':'confirmed', 'recalc_status':'applied'})
        self.assertEqual(database.get_subscription(1, self.path)['expires_at'], 105)

    def test_rejection_no_change_and_no_auto_retry(self):
        self.buy('first', 100)
        old = database.get_subscription(1, self.path)
        self.prepare('first')
        self.assertEqual(refunds.attempt_for_test('first', lambda user, charge: False, path=self.path), 'rejected')
        self.restart()
        self.assertEqual(self.prepare('first')['status'], 'rejected')
        self.assertFalse(refunds.begin_attempt('first', path=self.path))
        self.assertEqual(database.get_subscription(1, self.path), old)

    def test_access_and_legacy_are_not_guessed(self):
        database.grant_subscription(1, 2, self.path, now=100)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('DELETE FROM subscription_ledger')
            db.execute('DELETE FROM subscription_ledger_state')
        self.buy('first', 101)
        before = database.get_subscription(1, self.path)
        for admin,user in [(8,1),(9,2)]:
            with self.assertRaises(ValueError): refunds.prepare(admin,9,user,'first',path=self.path)
        self.prepare('first')
        self.assertEqual(refunds.confirm('first', 1, 50, 'XTR', path=self.path, now=120), 'manual_review')
        self.restart()
        self.assertEqual(database.get_subscription(1, self.path), before)
        self.assertTrue(vpn_alerts.due(path=self.path, now=121))

    def test_wrong_history_data_never_confirms(self):
        self.buy('first',100)
        self.prepare('first')
        for user,amount in [(2,50),(1,51)]:
            self.assertEqual(refunds.confirm('first',user,amount,'XTR',path=self.path,now=102), 'review')
        self.assertEqual(self.prepare('first')['status'], 'prepared')

    def test_old_history_without_verified_partner_needs_review(self):
        self.buy('first', 100)
        before = database.get_subscription(1, self.path)
        t = {'id':'first','direction':'outgoing','user_id':1,'order_id':None,'amount':50,'date':103}
        star_history.observe(t, path=self.path)
        star_history.finalize(path=self.path, now=105)
        self.assertEqual(database.get_subscription(1, self.path), before)
        self.assertTrue(vpn_alerts.due(path=self.path, now=106))
        t['refund_verified'] = True
        star_history.observe(t, path=self.path)
        star_history.finalize(path=self.path, now=107)
        self.assertEqual(database.get_subscription(1, self.path)['expires_at'], 107)

    def test_controller_error_after_refund_is_reported(self):
        self.buy('first', 100)
        key = base64.b64encode(bytes([1])*32).decode()
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("INSERT INTO vpn_devices(user_id,public_key,created_at,updated_at,access_state,vpn_ip,server_id) VALUES(1,?,1,1,'allowed','10.77.0.3/32','primary')", (key,))
        self.prepare('first')
        self.assertEqual(refunds.confirm('first',1,50,'XTR',path=self.path,now=120), 'applied')
        class Offline:
            def is_owned(self,*args): raise TimeoutError()
        self.assertEqual(vpn_reconcile.reconcile_one(1,Offline(),path=self.path,clock=lambda:121),'error')
        self.assertEqual(database.subscription_view(1,self.path)['vpn'],'unknown')
        self.assertEqual(vpn_alerts.due(path=self.path,now=121)[0]['action'],'revoke')

    def test_database_failure_before_and_after_request_and_restart(self):
        order = self.buy('first', 100)
        self.prepare('first')
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("CREATE TRIGGER fail_begin BEFORE UPDATE ON star_refunds BEGIN SELECT RAISE(ABORT,'offline'); END")
        with self.assertRaises(sqlite3.Error):
            refunds.begin_authorized(9,9,1,'first',path=self.path,now=101)
        self.assertEqual(self.prepare('first')['status'], 'prepared')
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('DROP TRIGGER fail_begin')
        self.assertTrue(refunds.begin_authorized(9,9,1,'first',path=self.path,now=102)['ready'])
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("CREATE TRIGGER fail_confirm BEFORE UPDATE ON test_subscriptions BEGIN SELECT RAISE(ABORT,'offline'); END")
        with self.assertRaises(sqlite3.Error):
            refunds.confirm('first',1,50,'XTR',order_id=order,path=self.path,now=103)
        self.restart()
        self.assertEqual(self.prepare('first')['status'], 'uncertain')
        self.assertFalse(refunds.begin_authorized(9,9,1,'first',path=self.path,now=104).get('ready',False))
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('DROP TRIGGER fail_confirm')
        self.assertEqual(refunds.confirm('first',1,50,'XTR',order_id=order,path=self.path,now=105),'applied')
        self.restart()
        self.assertEqual(refunds.confirm('first',1,50,'XTR',order_id=order,path=self.path,now=106),'applied')
        self.assertEqual(database.get_subscription(1,self.path)['expires_at'],105)

    def test_refund_update_payload_mismatch_persisted_for_review(self):
        self.buy('first', 100)
        before = database.get_subscription(1,self.path)
        self.assertEqual(refunds.confirm('first',1,50,'XTR',order_id='wrong-order',path=self.path,now=101),'review')
        self.restart()
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT status FROM refund_observations').fetchone()[0], 'review')
        self.assertEqual(database.get_subscription(1,self.path),before)


if __name__ == '__main__': unittest.main()
