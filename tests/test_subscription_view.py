import base64
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from app import database, payments


class SubscriptionViewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'temporary.sqlite3'
        database.initialize(self.path)
        database.register_user(1, self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_sources_and_renewal(self):
        self.assertIsNone(database.subscription_view(1, self.path)['subscription'])
        self.assertEqual(database.subscription_view(1, self.path)['vpn'], 'none')
        database.grant_subscription(1, 1, self.path, now=100)
        self.assertEqual(database.subscription_view(1, self.path)['source'], 'test')
        order = payments.create_order(1, 'days7', 42, path=self.path, now=101)
        payments.apply_payment(1, order['order_id'], 'XTR', 42, 'test-charge', path=self.path, now=102)
        self.assertEqual(database.subscription_view(1, self.path)['source'], 'mixed')
        order = payments.create_order(1, 'days7', 42, path=self.path, now=9999999)
        payments.apply_payment(1, order['order_id'], 'XTR', 42, 'second-charge', path=self.path, now=9999999)
        self.assertEqual(database.subscription_view(1, self.path)['source'], 'paid')
        database.initialize(self.path)
        self.assertEqual(database.subscription_view(1, self.path)['source'], 'paid')

    def test_device_unknown_error_and_confirmed(self):
        key = base64.b64encode(bytes(32)).decode()
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("INSERT INTO vpn_devices(user_id,public_key,created_at,updated_at,access_state) VALUES(1,?,1,1,'unknown')", (key,))
        self.assertEqual(database.subscription_view(1, self.path)['vpn'], 'unknown')
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("UPDATE vpn_devices SET access_state='allowed',last_error='controller_unavailable'")
        self.assertEqual(database.subscription_view(1, self.path)['vpn'], 'unknown')
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("UPDATE vpn_devices SET last_error=NULL")
        self.assertEqual(database.subscription_view(1, self.path)['vpn'], 'allowed')

    def test_legacy_migration_does_not_guess_or_delete(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('DROP TABLE subscription_sources')
            db.execute("INSERT INTO user_settings VALUES(1,'ru')")
            db.execute('INSERT INTO test_subscriptions VALUES(1,100,100000)')
        database.initialize(self.path)
        self.assertEqual(database.get_language(1, self.path), 'ru')
        self.assertEqual(database.get_subscription(1, self.path), {'started_at': 100, 'expires_at': 100000})
        self.assertEqual(database.subscription_view(1, self.path)['source'], 'unknown')
        database.grant_subscription(1, 1, self.path, now=101)
        self.assertEqual(database.subscription_view(1, self.path)['source'], 'unknown')
        database.grant_subscription(1, 1, self.path, now=9999999)
        self.assertEqual(database.subscription_view(1, self.path)['source'], 'test')


if __name__ == '__main__':
    unittest.main()
