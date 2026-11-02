import hashlib
import hmac
import json
import os
import tempfile
import time
import base64
import sqlite3
from contextlib import closing
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
        self.view_patch = patch.object(database, "subscription_view", lambda user: database.view_original(user, self.db))
        database.initialize_original = database.initialize
        database.get_original = database.get_language
        database.save_original = database.save_language
        database.view_original = database.subscription_view
        for p in (self.db_init, self.get_patch, self.save_patch, self.view_patch): p.start()
        self.client = TestClient(app)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        for p in (self.db_init, self.get_patch, self.save_patch, self.view_patch): p.stop()
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

    def test_account_requires_signed_identity_and_isolates_users(self):
        now = int(time.time())
        database.register_user(101, self.db)
        database.register_user(202, self.db)
        database.grant_subscription(101, 7, self.db, now=now)
        key = base64.b64encode(bytes([4]) * 32).decode()
        with closing(sqlite3.connect(self.db)) as connection, connection:
            connection.execute("INSERT INTO vpn_devices(user_id,public_key,created_at,updated_at,access_state) VALUES(101,?,?,?,'allowed')", (key,now,now))
        one = {"X-Telegram-Init-Data": signed_data(101)}
        two = {"X-Telegram-Init-Data": signed_data(202)}
        response = self.client.get('/api/account?user_id=202', headers=one)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['cache-control'], 'no-store')
        result = response.json()
        self.assertEqual(result['source'], 'test')
        self.assertEqual(result['subscription']['expires_at'], now + 7*86400)
        self.assertEqual(result['vpn'], 'allowed')
        self.assertNotIn('public_key', response.text)
        other = self.client.get('/api/account?user_id=101', headers=two).json()
        self.assertIsNone(other['subscription'])
        self.assertEqual(other['vpn'], 'none')
        with closing(sqlite3.connect(self.db)) as connection, connection:
            connection.execute("UPDATE vpn_devices SET last_error='controller_error' WHERE user_id=101")
        self.assertEqual(self.client.get('/api/account', headers=one).json()['vpn'], 'unknown')
        self.assertEqual(self.client.get('/api/account').status_code, 401)
        self.assertEqual(self.client.get('/api/account', headers={'X-Telegram-Init-Data': signed_data(101)+'&unexpected=1'}).status_code, 401)
        self.assertEqual(self.client.get('/api/account', headers={'X-Telegram-Init-Data': signed_data(101,auth_date=now-86401)}).status_code, 401)
        self.assertEqual(self.client.put('/api/settings?user_id=202', headers=one, json={'language':'es'}).status_code, 200)
        self.assertEqual(self.client.get('/api/settings', headers=one).json()['language'], 'es')
        self.assertEqual(self.client.get('/api/settings', headers=two).json()['language'], 'en')


if __name__ == "__main__":
    unittest.main()
