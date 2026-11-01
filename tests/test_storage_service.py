import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from contextlib import closing
from pathlib import Path

from app import database
from storage.service import execute


class StorageTests(unittest.TestCase):
    def test_vpn_controller_is_opt_in(self):
        command = {"action": "vpn_request", "user_id": 123, "public_key": "example"}
        with patch.dict('os.environ', {}, clear=True), patch('storage.service.vpn_provision.request_access', return_value={"status": "unavailable"}) as request:
            execute(command, 'unused')
            self.assertIsNone(request.call_args.kwargs['controller'])
        with patch.dict('os.environ', {'VPN_LOCAL_CONTROLLER': '1'}, clear=True), patch('storage.service.vpn_provision.request_access', return_value={"status": "unavailable"}) as request:
            execute(command, 'unused')
            from app.wg_controller import LocalWireGuardController
            self.assertIsInstance(request.call_args.kwargs['controller'], LocalWireGuardController)

    def test_languages_are_persistent_and_separate(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.sqlite3"
            database.initialize(path)
            self.assertIsNone(execute({"action": "get", "user_id": 1}, path))
            execute({"action": "set", "user_id": 1, "language": "kk"}, path)
            database.initialize(path)  # Повторный запуск не очищает таблицу.
            self.assertEqual(execute({"action": "get", "user_id": 1}, path), "kk")
            self.assertIsNone(execute({"action": "get", "user_id": 2}, path))
            with self.assertRaises(ValueError):
                execute({"action": "set", "user_id": 1, "language": "xx"}, path)

    def test_new_process_reads_previous_process_data(self):
        # Запускаем именно Python-сервис дважды с временной базой, не затрагивая данные пользователя.
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "test.sqlite3")
            script = "import sys; from pathlib import Path; from app import database; database.DATABASE_PATH=Path(sys.argv.pop()); from storage.service import main; main()"
            def run(command):
                return subprocess.run([sys.executable, "-c", script, path], input=json.dumps(command) + "\n", text=True, capture_output=True, check=True)
            self.assertTrue(json.loads(run({"action":"set", "user_id":123, "language":"de"}).stdout)["ok"])
            self.assertEqual(json.loads(run({"action":"get", "user_id":123}).stdout)["language"], "de")

    def test_migration_grant_extension_and_expiry(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "old.sqlite3"
            with closing(sqlite3.connect(path)) as db:
                with db:
                    db.execute("CREATE TABLE user_settings (user_id INTEGER PRIMARY KEY, language TEXT NOT NULL)")
                    db.execute("INSERT INTO user_settings VALUES (11, 'kk')")
            database.initialize(path)
            database.initialize(path)
            self.assertEqual(database.get_language(11, path), "kk")
            self.assertIsNone(database.grant_subscription(999, 7, path, now=1000))
            first = database.grant_subscription(11, 7, path, now=1000)
            self.assertEqual(first, {"started_at": 1000, "expires_at": 1000 + 7 * 86400})
            extended = database.grant_subscription(11, 2, path, now=2000)
            self.assertEqual(extended, {"started_at": 1000, "expires_at": 1000 + 9 * 86400})
            # Ровно в момент окончания подписка уже истекла.
            expired_at = extended["expires_at"]
            restarted = database.grant_subscription(11, 1, path, now=expired_at)
            self.assertEqual(restarted, {"started_at": expired_at, "expires_at": expired_at + 86400})
            database.initialize(path)
            self.assertEqual(database.get_subscription(11, path), restarted)
            self.assertEqual(database.get_language(11, path), "kk")
            for days in (0, -1, 366, 1.5, True, None):
                with self.assertRaises(ValueError):
                    database.grant_subscription(11, days, path, now=1000)
            self.assertEqual(database.get_subscription(11, path), restarted)

    def test_failed_write_does_not_create_subscription(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fail.sqlite3"
            database.initialize(path)
            database.register_user(11, path)
            with closing(sqlite3.connect(path)) as db:
                with db:
                    db.execute("CREATE TRIGGER fail_grant BEFORE INSERT ON test_subscriptions BEGIN SELECT RAISE(ABORT, 'test'); END")
            with self.assertRaises(sqlite3.IntegrityError):
                database.grant_subscription(11, 7, path, now=1000)
            self.assertIsNone(database.get_subscription(11, path))

    def test_subscription_survives_python_process_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "test.sqlite3")
            script = "import sys; from pathlib import Path; from app import database; database.DATABASE_PATH=Path(sys.argv.pop()); from storage.service import main; main()"
            def run(command):
                result = subprocess.run([sys.executable, "-c", script, path], input=json.dumps(command) + "\n", text=True, capture_output=True, check=True)
                return json.loads(result.stdout)
            self.assertTrue(run({"action": "register", "user_id": 123})["value"])
            granted = run({"action": "grant", "user_id": 123, "days": 7})["value"]
            self.assertEqual(run({"action": "subscription", "user_id": 123})["value"], granted)
            self.assertIsNone(run({"action": "grant", "user_id": 999, "days": 7})["value"])
            self.assertFalse(run({"action": "grant", "user_id": 123, "days": 366})["ok"])


if __name__ == "__main__":
    unittest.main()
