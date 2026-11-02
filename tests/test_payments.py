import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from app import database, payments, vpn_reconcile, vpn_alerts
import base64


class PaymentsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'test.sqlite3'
        database.initialize(self.path)
        database.register_user(1, self.path)
        database.register_user(2, self.path)
    def tearDown(self): self.tmp.cleanup()
    def order(self, plan='days7'): return payments.create_order(1, plan, 50, path=self.path, now=1000)
    def test_each_plan_atomic_and_restart(self):
        for plan,days in payments.PLAN_DAYS.items():
            with self.subTest(plan=plan):
                database.register_user(days, self.path)
                order=payments.create_order(days,plan,50,path=self.path,now=1000)
                self.assertTrue(payments.valid_order(days,order['order_id'],'XTR',50,path=self.path))
                result=payments.apply_payment(days,order['order_id'],'XTR',50,'charge-'+plan,path=self.path,now=1001)
                self.assertEqual(result['expires_at'],1001+days*86400)
                database.initialize(self.path)
                self.assertEqual(database.get_subscription(days,self.path)['expires_at'],result['expires_at'])
                self.assertEqual(payments.apply_payment(days,order['order_id'],'XTR',50,'charge-'+plan,path=self.path,now=1002)['status'],'duplicate')
    def test_existing_active_and_expired(self):
        database.grant_subscription(1,1,self.path,now=1000)
        a=self.order(); r=payments.apply_payment(1,a['order_id'],'XTR',50,'first',path=self.path,now=2000)
        self.assertEqual(r['expires_at'],1000+8*86400)
        b=self.order(); r=payments.apply_payment(1,b['order_id'],'XTR',50,'second',path=self.path,now=1000000)
        self.assertEqual(r['expires_at'],1000000+7*86400)
    def test_invalid_data_and_duplicate_charge(self):
        o=self.order()['order_id']
        for user,order,currency,amount in [(2,o,'XTR',50),(1,'unknown','XTR',50),(1,o,'USD',50),(1,o,'XTR',51)]:
            self.assertFalse(payments.valid_order(user,order,currency,amount,path=self.path))
            with self.assertRaises(ValueError): payments.apply_payment(user,order,currency,amount,'charge',path=self.path,now=1000)
        self.assertIsNone(database.get_subscription(1,self.path))
        payments.apply_payment(1,o,'XTR',50,'charge',path=self.path,now=1000)
        other=self.order()['order_id']
        with self.assertRaises(ValueError): payments.apply_payment(1,other,'XTR',50,'charge',path=self.path,now=1000)
    def test_write_failure_rolls_back_everything(self):
        o=self.order()['order_id']
        with closing(sqlite3.connect(self.path)) as db:
            with db: db.execute("CREATE TRIGGER fail_sub BEFORE INSERT ON test_subscriptions BEGIN SELECT RAISE(ABORT,'fail'); END")
        with self.assertRaises(sqlite3.Error): payments.apply_payment(1,o,'XTR',50,'charge',path=self.path,now=1000)
        self.assertTrue(payments.valid_order(1,o,'XTR',50,path=self.path))
        with closing(sqlite3.connect(self.path)) as db: self.assertEqual(db.execute('SELECT COUNT(*) FROM payments').fetchone()[0],0)
    def test_controller_failure_does_not_lose_paid_subscription(self):
        key=base64.b64encode(b'x'*32).decode()
        with closing(sqlite3.connect(self.path)) as db:
            with db: db.execute("INSERT INTO vpn_devices(user_id,public_key,created_at,updated_at,access_state,vpn_ip,server_id) VALUES(1,?,1000,1000,'revoked','10.77.0.3/32','primary')",(key,))
        order=self.order()['order_id']
        paid=payments.apply_payment(1,order,'XTR',50,'charge',path=self.path,now=1000)
        class Offline:
            def is_owned(self,*args): raise TimeoutError()
        self.assertEqual(vpn_reconcile.reconcile_one(1,Offline(),path=self.path,clock=lambda:1001),'error')
        self.assertEqual(database.get_subscription(1,self.path)['expires_at'],paid['expires_at'])
        self.assertEqual(vpn_alerts.due(path=self.path,now=1001)[0]['action'],'restore')
    def test_receipt_survives_failed_fulfillment_and_restart(self):
        order=self.order()['order_id']
        with closing(sqlite3.connect(self.path)) as db:
            with db: db.execute("CREATE TRIGGER fail_sub BEFORE INSERT ON test_subscriptions BEGIN SELECT RAISE(ABORT,'fail'); END")
        self.assertEqual(payments.accept_payment(1,order,'XTR',50,'charge',path=self.path,now=1000)['status'],'pending')
        self.assertIsNone(database.get_subscription(1,self.path))
        self.assertEqual(vpn_alerts.due(path=self.path,now=1000)[0]['action'],'payment')
        with closing(sqlite3.connect(self.path)) as db:
            with db: vpn_alerts.resolve(db,1,1000)
        self.assertEqual(vpn_alerts.due(path=self.path,now=1000)[0]['action'],'payment')
        with closing(sqlite3.connect(self.path)) as db:
            with db: db.execute('DROP TRIGGER fail_sub')
        database.initialize(self.path)
        self.assertEqual(payments.retry_pending(path=self.path,now=1001)[0]['status'],'paid')
        self.assertEqual(database.get_subscription(1,self.path)['expires_at'],1001+7*86400)
        self.assertEqual(payments.accept_payment(1,order,'XTR',50,'charge',path=self.path,now=1002)['status'],'duplicate')
        self.assertEqual(database.get_subscription(1,self.path)['expires_at'],1001+7*86400)


if __name__ == '__main__': unittest.main()
