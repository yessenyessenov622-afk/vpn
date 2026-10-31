import base64
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from app import database, vpn_devices, vpn_policy


def public_key(value):
    # Искусственные байты для проверки формата, не настоящие ключи.
    return base64.b64encode(bytes([value]) * 32).decode("ascii")


class VPNDevicesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "test.sqlite3"
        database.initialize(self.path)
        database.register_user(101, self.path)
        database.register_user(202, self.path)
        self.key = public_key(1)

    def tearDown(self):
        self.temp.cleanup()

    def add(self, user_id=101, key=None):
        return vpn_devices.add_device(user_id, self.key if key is None else key, path=self.path, now=1000)

    def test_add_and_read_unknown_device_after_reopening(self):
        device = self.add()
        self.assertEqual(device, {"user_id": 101, "public_key": self.key, "created_at": 1000, "updated_at": 1000, "access_state": "unknown", "last_error": None})
        database.initialize(self.path)
        self.assertEqual(vpn_devices.get_device(101, path=self.path), device)
        self.assertIsNone(vpn_devices.get_device(202, path=self.path))

    def test_one_device_per_user_and_key_unique(self):
        self.add()
        with self.assertRaisesRegex(vpn_devices.DeviceError, "уже есть устройство"):
            self.add(key=public_key(2))
        with self.assertRaisesRegex(vpn_devices.DeviceError, "ключ уже принадлежит"):
            self.add(user_id=202)
        self.assertIsNone(vpn_devices.get_device(202, path=self.path))
        # Ограничения SQLite защищают от повторов и в обход функций.
        with closing(sqlite3.connect(self.path)) as conn:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("INSERT INTO vpn_devices(user_id,public_key,created_at,updated_at) VALUES (202,?,1000,1000)", (self.key,))

    def test_invalid_user_and_public_keys(self):
        for user_id in (0, -1, 1.5, True, 2**52 + 1):
            with self.subTest(user_id=user_id), self.assertRaises(vpn_devices.DeviceError):
                self.add(user_id=user_id)
        with self.assertRaisesRegex(vpn_devices.DeviceError, "не зарегистрирован"):
            self.add(user_id=303)
        for key in (None, "", "abc", "!" * 44, base64.b64encode(b"short").decode(), self.key[:-1], self.key[:-1] + "A", self.key[:5] + "\n" + self.key[5:]):
            with self.subTest(key=key), self.assertRaises(vpn_devices.DeviceError):
                vpn_devices.add_device(101, key, path=self.path, now=1000)
        # Неканонические последние биты Base64 отклоняются.
        with self.assertRaises(vpn_devices.DeviceError):
            self.add(key=self.key[:-2] + "R=")
        self.assertIsNone(vpn_devices.get_device(101, path=self.path))

    def test_confirmation_required_and_error_preserves_state(self):
        self.add()
        for confirmation in (False, None, 1):
            with self.assertRaisesRegex(vpn_devices.DeviceError, "подтверждённое состояние"):
                vpn_devices.save_confirmed_state(101, self.key, True, controller_confirmed=confirmation, path=self.path, now=1001)
        self.assertEqual(vpn_devices.get_device(101, path=self.path)["access_state"], "unknown")
        device = vpn_devices.save_confirmed_state(101, self.key, True, controller_confirmed=True, path=self.path, now=1002)
        self.assertEqual(device["access_state"], "allowed")
        device = vpn_devices.record_error(101, self.key, "confirmation_lost", path=self.path, now=1003)
        self.assertEqual(device["access_state"], "allowed")
        self.assertEqual(device["last_error"], "confirmation_lost")
        self.assertEqual(device["updated_at"], 1003)
        with self.assertRaises(vpn_devices.DeviceError):
            vpn_devices.record_error(101, self.key, "arbitrary error potentially containing secrets", path=self.path, now=1004)
        with self.assertRaises(vpn_devices.DeviceError):
            vpn_devices.save_confirmed_state(101, public_key(9), False, controller_confirmed=True, path=self.path, now=1004)
        confirmed = vpn_devices.save_confirmed_state(101, self.key, False, controller_confirmed=True, path=self.path, now=1005)
        self.assertEqual(confirmed["access_state"], "revoked")
        self.assertIsNone(confirmed["last_error"])
        self.assertEqual(confirmed["created_at"], 1000)

    def test_policy_with_active_expired_unknown_and_failed_state(self):
        self.add()
        database.grant_subscription(101, 1, self.path, now=1000)
        record = vpn_devices.list_devices_for_check(path=self.path)[0]
        self.assertEqual(vpn_devices.decide_for_device(record, now=1001).action, vpn_policy.Action.VERIFY)
        decision = vpn_devices.decide_for_device(record, now=1001)
        class NoCalls:
            def set_access(self, device, enabled):
                raise AssertionError("Unknown state must not trigger changes")
        self.assertEqual(vpn_policy.apply_decision(decision, NoCalls()).status, vpn_policy.ResultStatus.NEEDS_CHECK)
        vpn_devices.save_confirmed_state(101, self.key, False, controller_confirmed=True, path=self.path, now=1002)
        record = vpn_devices.list_devices_for_check(path=self.path)[0]
        self.assertEqual(vpn_devices.decide_for_device(record, now=1003).action, vpn_policy.Action.ENABLE)
        vpn_devices.save_confirmed_state(101, self.key, True, controller_confirmed=True, path=self.path, now=1004)
        record = vpn_devices.list_devices_for_check(path=self.path)[0]
        self.assertEqual(vpn_devices.decide_for_device(record, now=1000 + 86400).action, vpn_policy.Action.DISABLE)
        vpn_devices.record_error(101, self.key, "confirmation_lost", path=self.path, now=1005)
        record = vpn_devices.list_devices_for_check(path=self.path)[0]
        self.assertEqual(record["access_state"], "allowed")
        self.assertEqual(vpn_devices.decide_for_device(record, now=1000 + 86400).action, vpn_policy.Action.VERIFY)

    def test_reconciliation_reads_each_users_own_subscription(self):
        self.add()
        self.add(user_id=202, key=public_key(2))
        vpn_devices.save_confirmed_state(101, self.key, False, controller_confirmed=True, path=self.path, now=1001)
        vpn_devices.save_confirmed_state(202, public_key(2), True, controller_confirmed=True, path=self.path, now=1001)
        database.grant_subscription(101, 1, self.path, now=1000)
        records = vpn_devices.list_devices_for_check(path=self.path)
        self.assertEqual([record["user_id"] for record in records], [101, 202])
        self.assertEqual(vpn_devices.decide_for_device(records[0], now=1002).action, vpn_policy.Action.ENABLE)
        self.assertIsNone(records[1]["expires_at"])
        self.assertEqual(vpn_devices.decide_for_device(records[1], now=1002).action, vpn_policy.Action.DISABLE)

    def test_migration_preserves_old_users_languages_and_subscriptions(self):
        old = Path(self.temp.name) / "old.sqlite3"
        with closing(sqlite3.connect(old)) as conn:
            with conn:
                conn.execute("CREATE TABLE registered_users (user_id INTEGER PRIMARY KEY)")
                conn.execute("CREATE TABLE user_settings (user_id INTEGER PRIMARY KEY, language TEXT NOT NULL)")
                conn.execute("CREATE TABLE test_subscriptions (user_id INTEGER PRIMARY KEY, started_at INTEGER NOT NULL, expires_at INTEGER NOT NULL)")
                conn.execute("INSERT INTO registered_users VALUES (101)")
                conn.execute("INSERT INTO user_settings VALUES (101, 'kk')")
                conn.execute("INSERT INTO test_subscriptions VALUES (101, 1000, 2000)")
        database.initialize(old)
        database.initialize(old)
        self.assertEqual(database.get_language(101, old), "kk")
        self.assertEqual(database.get_subscription(101, old), {"started_at": 1000, "expires_at": 2000})
        self.assertEqual(vpn_devices.add_device(101, self.key, path=old, now=1000)["access_state"], "unknown")
        self.assertEqual(database.get_subscription(101, old), {"started_at": 1000, "expires_at": 2000})


if __name__ == "__main__":
    unittest.main()
