import hashlib
import hmac
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlencode

from fastapi.testclient import TestClient

from app import database
from app.auth import AuthError, validate_init_data
from app.main import app
from bot import valid_url

TOKEN = "123456:test-token"


def signed_data(user_id=123, language="en", auth_date=None):
    fields = {"auth_date": str(int(time.time()) if auth_date is None else auth_date), "user": json.dumps({"id": user_id, "language_code": language}, separators=(",", ":"))}
    check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


class AuthTests(unittest.TestCase):
    def test_valid_signature_and_tampering(self):
        raw = signed_data()
        self.assertEqual(validate_init_data(raw, TOKEN)["id"], 123)
        with self.assertRaises(AuthError):
            validate_init_data(raw.replace("123%2C", "124%2C"), TOKEN)
        with self.assertRaises(AuthError):
            validate_init_data(raw + "&auth_date=1", TOKEN)

    def test_expired_and_future(self):
        for timestamp in (int(time.time()) - 86401, int(time.time()) + 60):
            with self.assertRaises(AuthError):
                validate_init_data(signed_data(auth_date=timestamp), TOKEN)

    def test_url_configuration(self):
        self.assertTrue(valid_url("https://example.com/"))
        for url in ("", "http://example.com", "https://localhost", "https://127.0.0.1", "https://example.com:bad"):
            self.assertFalse(valid_url(url))


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "test.sqlite3"
        self.env = patch.dict(os.environ, {"BOT_TOKEN": TOKEN})
        self.env.start()
        self.db_init = patch.object(database, "initialize", lambda: database.initialize_original(self.db))
        self.get_patch = patch.object(database, "get_language", lambda user: database.get_original(user, self.db))
        self.save_patch = patch.object(database, "save_language", lambda user, lang: database.save_original(user, lang, self.db))
        database.initialize_original = database.initialize
        database.get_original = database.get_language
        database.save_original = database.save_language
        for p in (self.db_init, self.get_patch, self.save_patch): p.start()
        self.client = TestClient(app)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        for p in (self.db_init, self.get_patch, self.save_patch): p.stop()
        self.env.stop()
        self.temp.cleanup()

    def test_separate_users_persistence_and_rejection(self):
        headers = {"X-Telegram-Init-Data": signed_data(101, "kk")}
        other = {"X-Telegram-Init-Data": signed_data(202, "xx")}
        self.assertEqual(self.client.get("/api/settings", headers=headers).json(), {"language": "kk"})
        self.assertEqual(self.client.get("/api/settings", headers=other).json(), {"language": "ru"})
        self.assertEqual(self.client.put("/api/settings", headers=headers, json={"language": "de"}).status_code, 200)
        self.assertEqual(self.client.get("/api/settings", headers=headers).json(), {"language": "de"})
        self.assertEqual(self.client.get("/api/settings", headers=other).json(), {"language": "ru"})
        self.assertEqual(self.client.put("/api/settings", headers=headers, json={"language": "bad"}).status_code, 400)
        self.assertEqual(self.client.get("/api/settings").status_code, 401)
        self.assertEqual(self.client.put("/api/settings", headers={"X-Telegram-Init-Data": "user=123"}, json={"language": "en"}).status_code, 401)


if __name__ == "__main__":
    unittest.main()
