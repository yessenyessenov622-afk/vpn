import base64
import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path

from app import database, vpn_devices, vpn_provision


def key(number):
    return base64.b64encode(bytes([number]) * 32).decode("ascii")


class FakeController:
    """Имитация сервера, доступная только тестам."""
    def __init__(self):
        self.peers = {key(9): "10.77.0.2/32"}
        self.adds = 0
        self.fail = None
        self.lock = threading.Lock()

    def list_peers(self):
        with self.lock:
            if self.fail == "list": raise TimeoutError()
            return dict(self.peers)

    def server_details(self):
        return {"public_key": key(8), "endpoint": "192.0.2.1:51820"}

    def add_if_free(self, public_key, address, expires_at):
        with self.lock:
            self.adds += 1
            if self.fail == "before": raise TimeoutError()
            if address in self.peers.values() or public_key in self.peers: return False
            self.peers[public_key] = address
            if self.fail == "after": raise TimeoutError()
            return True


class VPNProvisionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "test.sqlite3"
        database.initialize(self.db)
        for user in (101, 202):
            database.register_user(user, self.db)
            database.grant_subscription(user, 1, self.db, now=1000)
        self.controller = FakeController()

    def tearDown(self):
        self.temp.cleanup()

    def request(self, user, public_key, *, controller=None, now=1001):
        return vpn_provision.request_access(user, public_key, controller=self.controller if controller is None else controller, path=self.db, clock=lambda: now)

    def test_active_subscription_confirmation_and_idempotency(self):
        result = self.request(101, key(1))
        self.assertEqual(result["status"], "confirmed")
        self.assertEqual(result["address"], "10.77.0.3/32")
        self.assertEqual(self.controller.peers[key(9)], "10.77.0.2/32")
        self.assertEqual(vpn_devices.get_device(101, path=self.db)["access_state"], "allowed")
        self.assertEqual(self.request(101, key(1)), result)
        self.assertEqual(self.controller.adds, 1)

    def test_expired_missing_invalid_and_unavailable_do_not_create_device(self):
        self.assertEqual(self.request(101, key(1), now=87400)["status"], "inactive")
        database.register_user(303, self.db)
        self.assertEqual(self.request(303, key(3))["status"], "inactive")
        self.assertEqual(self.request(101, "invalid")["status"], "invalid_key")
        self.assertEqual(vpn_provision.request_access(101, key(1), path=self.db, clock=lambda: 1001)["status"], "unavailable")
        self.assertIsNone(vpn_devices.get_device(101, path=self.db))
        self.assertEqual(self.controller.adds, 0)

    def test_conflicting_public_key_and_existing_peer_cannot_be_adopted(self):
        self.assertEqual(self.request(101, key(9))["status"], "key_in_use")
        self.assertIsNone(vpn_devices.get_device(101, path=self.db))
        self.assertEqual(self.request(101, key(1))["status"], "confirmed")
        self.assertEqual(self.request(202, key(1))["status"], "key_in_use")
        self.assertEqual(self.request(101, key(2))["status"], "device_exists")
        self.assertIsNone(vpn_devices.get_device(202, path=self.db))

    def test_pool_conflicts_and_reserved_ip(self):
        first = self.request(101, key(1))
        self.assertEqual(first["address"], "10.77.0.3/32")
        self.assertEqual(self.request(202, key(2))["address"], "10.77.0.4/32")
        self.controller.peers[key(7)] = "10.77.0.3/32"
        self.assertEqual(self.request(101, key(1))["status"], "ip_in_use")
        self.assertEqual(self.controller.peers[key(9)], "10.77.0.2/32")

    def test_two_concurrent_users_get_unique_addresses(self):
        barrier = threading.Barrier(2)
        def run(user, value):
            barrier.wait()
            return self.request(user, key(value))
        with ThreadPoolExecutor(max_workers=2) as pool:
            a = pool.submit(run, 101, 1)
            b = pool.submit(run, 202, 2)
            results = [a.result(), b.result()]
        self.assertEqual({r["status"] for r in results}, {"confirmed"})
        self.assertEqual({r["address"] for r in results}, {"10.77.0.3/32", "10.77.0.4/32"})

    def test_timeout_and_retry_keep_unconfirmed_until_verified(self):
        self.controller.fail = "after"
        self.assertEqual(self.request(101, key(1))["status"], "unconfirmed")
        device = vpn_devices.get_device(101, path=self.db)
        self.assertEqual(device["access_state"], "unknown")
        self.assertEqual(device["last_error"], "confirmation_lost")
        self.controller.fail = None
        self.assertEqual(self.request(101, key(1))["status"], "confirmed")
        self.assertEqual(self.controller.adds, 1)
        self.assertEqual(vpn_devices.get_device(101, path=self.db)["access_state"], "allowed")

    def test_process_interruption_keeps_reservation_for_retry(self):
        class Interrupted(BaseException):
            pass

        original = self.controller.add_if_free

        def interrupted_after_add(public_key, address, expires_at):
            original(public_key, address, expires_at)
            raise Interrupted()

        self.controller.add_if_free = interrupted_after_add
        with self.assertRaises(Interrupted):
            self.request(101, key(1))
        device = vpn_devices.get_device(101, path=self.db)
        with closing(sqlite3.connect(self.db)) as conn:
            address = conn.execute("SELECT vpn_ip FROM vpn_devices WHERE user_id = 101").fetchone()[0]
        self.assertEqual(address, "10.77.0.3/32")
        self.assertEqual(device["access_state"], "unknown")
        self.controller.add_if_free = original
        self.assertEqual(self.request(101, key(1))["status"], "confirmed")
        self.assertEqual(self.request(202, key(2))["address"], "10.77.0.4/32")

    def test_timeout_without_server_response_is_not_success(self):
        self.controller.fail = "list"
        self.assertEqual(self.request(101, key(1))["status"], "unavailable")
        self.assertIsNone(vpn_devices.get_device(101, path=self.db))

    def test_subscription_rechecked_immediately_before_controller_write(self):
        values = iter([1001, 87400])
        result = vpn_provision.request_access(101, key(1), controller=self.controller, path=self.db, clock=lambda: next(values))
        self.assertEqual(result["status"], "inactive")
        self.assertEqual(self.controller.adds, 0)

    def test_no_confirmation_is_not_reported_as_success(self):
        self.controller.fail = "before"
        result = self.request(101, key(1))
        self.assertEqual(result["status"], "unconfirmed")
        self.assertNotEqual(vpn_devices.get_device(101, path=self.db)["access_state"], "allowed")

    def test_expiration_during_server_operation_is_not_reported_as_success(self):
        values = iter([1001, 1001, 1001, 87400, 87400])
        result = vpn_provision.request_access(101, key(1), controller=self.controller, path=self.db, clock=lambda: next(values))
        self.assertEqual(result["status"], "unconfirmed")
        self.assertEqual(vpn_devices.get_device(101, path=self.db)["last_error"], "confirmation_lost")
        # A server may have applied the change; explicit reconciliation is needed.
        self.assertEqual(self.controller.peers[key(1)], "10.77.0.3/32")

    def test_existing_vpn_devices_migrate_without_losing_rows(self):
        old = Path(self.temp.name) / "old.sqlite3"
        with closing(sqlite3.connect(old)) as conn:
            with conn:
                conn.execute("CREATE TABLE registered_users (user_id INTEGER PRIMARY KEY)")
                conn.execute("CREATE TABLE user_settings (user_id INTEGER PRIMARY KEY, language TEXT NOT NULL)")
                conn.execute("CREATE TABLE test_subscriptions (user_id INTEGER PRIMARY KEY, started_at INTEGER NOT NULL, expires_at INTEGER NOT NULL)")
                conn.execute("CREATE TABLE vpn_devices (user_id INTEGER PRIMARY KEY, public_key TEXT UNIQUE NOT NULL, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL, access_state TEXT NOT NULL DEFAULT 'unknown', last_error TEXT)")
                conn.execute("INSERT INTO registered_users VALUES (101)")
                conn.execute("INSERT INTO test_subscriptions VALUES (101,1000,87400)")
                conn.execute("INSERT INTO vpn_devices VALUES (101,?,1000,1000,'unknown',NULL)", (key(1),))
        database.initialize(old)
        database.initialize(old)
        self.assertEqual(vpn_devices.get_device(101, path=old)["public_key"], key(1))
        self.assertEqual(database.get_subscription(101, old)["expires_at"], 87400)
        with closing(sqlite3.connect(old)) as conn:
            row = conn.execute("SELECT vpn_ip,server_id FROM vpn_devices WHERE user_id = 101").fetchone()
        self.assertEqual(row, (None, "primary"))

    def test_database_enforces_unique_reserved_address(self):
        self.request(101, key(1))
        vpn_devices.add_device(202, key(2), path=self.db, now=1000)
        with closing(sqlite3.connect(self.db)) as conn:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("UPDATE vpn_devices SET vpn_ip = ? WHERE user_id = ?", ("10.77.0.3/32", 202))


if __name__ == "__main__":
    unittest.main()
