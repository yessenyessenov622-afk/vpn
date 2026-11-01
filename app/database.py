import sqlite3
import time
from contextlib import closing
from pathlib import Path

DATABASE_PATH = Path(__file__).resolve().parent.parent / "users.sqlite3"


def initialize(path=DATABASE_PATH):
    with closing(sqlite3.connect(path)) as connection:
        with connection:
            connection.execute("CREATE TABLE IF NOT EXISTS user_settings (user_id INTEGER PRIMARY KEY, language TEXT NOT NULL)")
            connection.execute("CREATE TABLE IF NOT EXISTS registered_users (user_id INTEGER PRIMARY KEY)")
            connection.execute("CREATE TABLE IF NOT EXISTS test_subscriptions (user_id INTEGER PRIMARY KEY, started_at INTEGER NOT NULL, expires_at INTEGER NOT NULL)")
            connection.execute("""CREATE TABLE IF NOT EXISTS vpn_alerts (
                user_id INTEGER NOT NULL, action TEXT NOT NULL, code TEXT NOT NULL,
                active INTEGER NOT NULL, occurred_at INTEGER NOT NULL, resolved_at INTEGER,
                last_sent INTEGER, notified INTEGER NOT NULL DEFAULT 0, version INTEGER NOT NULL,
                PRIMARY KEY(user_id, action, code)
            )""")
            connection.execute("""CREATE TABLE IF NOT EXISTS vpn_devices (
                user_id INTEGER PRIMARY KEY REFERENCES registered_users(user_id),
                public_key TEXT NOT NULL UNIQUE,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                access_state TEXT NOT NULL DEFAULT 'unknown' CHECK (access_state IN ('unknown', 'allowed', 'revoked')),
                last_error TEXT
            )""")
            columns = {row[1] for row in connection.execute("PRAGMA table_info(vpn_devices)")}
            if "vpn_ip" not in columns:
                connection.execute("ALTER TABLE vpn_devices ADD COLUMN vpn_ip TEXT")
            if "server_id" not in columns:
                connection.execute("ALTER TABLE vpn_devices ADD COLUMN server_id TEXT NOT NULL DEFAULT 'primary'")
            connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS vpn_devices_server_ip ON vpn_devices(server_id, vpn_ip) WHERE vpn_ip IS NOT NULL")
            # Ранее записывались только пользователи, вручную выбравшие язык.
            connection.execute("INSERT OR IGNORE INTO registered_users (user_id) SELECT user_id FROM user_settings")


def get_language(user_id, path=DATABASE_PATH):
    with closing(sqlite3.connect(path)) as connection:
        row = connection.execute("SELECT language FROM user_settings WHERE user_id = ?", (user_id,)).fetchone()
        return row[0] if row else None


def save_language(user_id, language, path=DATABASE_PATH):
    with closing(sqlite3.connect(path)) as connection:
        with connection:
            connection.execute("INSERT INTO user_settings (user_id, language) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET language = excluded.language", (user_id, language))


def register_user(user_id, path=DATABASE_PATH):
    with closing(sqlite3.connect(path)) as connection:
        with connection:
            connection.execute("INSERT OR IGNORE INTO registered_users (user_id) VALUES (?)", (user_id,))


def get_subscription(user_id, path=DATABASE_PATH):
    with closing(sqlite3.connect(path)) as connection:
        row = connection.execute("SELECT started_at, expires_at FROM test_subscriptions WHERE user_id = ?", (user_id,)).fetchone()
        return {"started_at": row[0], "expires_at": row[1]} if row else None


def grant_subscription(user_id, days, path=DATABASE_PATH, *, now=None):
    if type(user_id) is not int or not 0 < user_id <= 2**52 or type(days) is not int or not 1 <= days <= 365:
        raise ValueError("Invalid user or days")
    current = int(time.time()) if now is None else now
    with closing(sqlite3.connect(path)) as connection:
        # Блокировка записи предотвращает потерю дней при одновременных выдачах.
        connection.execute("BEGIN IMMEDIATE")
        try:
            if not connection.execute("SELECT 1 FROM registered_users WHERE user_id = ?", (user_id,)).fetchone():
                connection.rollback()
                return None
            row = connection.execute("SELECT started_at, expires_at FROM test_subscriptions WHERE user_id = ?", (user_id,)).fetchone()
            active = row is not None and row[1] > current
            started_at = row[0] if active else current
            expires_at = (row[1] if active else current) + days * 86400
            if expires_at > 253402300799:
                raise ValueError("Expiration is out of range")
            connection.execute("INSERT INTO test_subscriptions (user_id, started_at, expires_at) VALUES (?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET started_at = excluded.started_at, expires_at = excluded.expires_at", (user_id, started_at, expires_at))
            connection.commit()
            return {"started_at": started_at, "expires_at": expires_at}
        except Exception:
            connection.rollback()
            raise
