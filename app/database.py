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
            connection.execute("CREATE TABLE IF NOT EXISTS subscription_sources (user_id INTEGER PRIMARY KEY, source TEXT NOT NULL CHECK(source IN ('test','paid','mixed','unknown')))")
            connection.execute("""CREATE TABLE IF NOT EXISTS subscription_ledger_state (
                user_id INTEGER PRIMARY KEY, complete INTEGER NOT NULL, expected_start INTEGER, expected_end INTEGER)""")
            connection.execute("""CREATE TABLE IF NOT EXISTS subscription_ledger (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, kind TEXT NOT NULL,
                charge_id TEXT UNIQUE, occurred_at INTEGER NOT NULL, seconds INTEGER NOT NULL)""")
            connection.execute("""CREATE TABLE IF NOT EXISTS star_refunds (
                charge_id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, status TEXT NOT NULL,
                updated_at INTEGER NOT NULL, recalc_status TEXT NOT NULL DEFAULT 'pending')""")
            connection.execute("""CREATE TABLE IF NOT EXISTS refund_observations (
                charge_id TEXT NOT NULL, user_id INTEGER NOT NULL, amount INTEGER NOT NULL,
                currency TEXT NOT NULL, order_id TEXT NOT NULL, status TEXT NOT NULL,
                PRIMARY KEY(charge_id,user_id,amount,currency,order_id))""")
            connection.execute("""CREATE TABLE IF NOT EXISTS payment_orders (
                order_id TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES registered_users(user_id),
                plan_id TEXT NOT NULL, days INTEGER NOT NULL, currency TEXT NOT NULL,
                amount INTEGER NOT NULL, created_at INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'pending'
            )""")
            connection.execute("""CREATE TABLE IF NOT EXISTS payments (
                charge_id TEXT PRIMARY KEY, order_id TEXT NOT NULL UNIQUE REFERENCES payment_orders(order_id),
                user_id INTEGER NOT NULL, currency TEXT NOT NULL, amount INTEGER NOT NULL,
                paid_at INTEGER NOT NULL, started_at INTEGER NOT NULL, expires_at INTEGER NOT NULL
            )""")
            connection.execute("""CREATE TABLE IF NOT EXISTS payment_inbox (
                charge_id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, order_id TEXT NOT NULL,
                currency TEXT NOT NULL, amount INTEGER NOT NULL, received_at INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending'
            )""")
            connection.execute("""CREATE TABLE IF NOT EXISTS star_history (
                transaction_id TEXT NOT NULL, direction TEXT NOT NULL,
                user_id INTEGER, order_id TEXT, amount INTEGER, occurred_at INTEGER,
                status TEXT NOT NULL DEFAULT 'observed', PRIMARY KEY(transaction_id,direction)
            )""")
            if 'refund_verified' not in {row[1] for row in connection.execute('PRAGMA table_info(star_history)')}:
                connection.execute('ALTER TABLE star_history ADD COLUMN refund_verified INTEGER NOT NULL DEFAULT 0')
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


def subscription_view(user_id, path=DATABASE_PATH):
    with closing(sqlite3.connect(path)) as connection:
        row = connection.execute("""SELECT s.started_at,s.expires_at,ss.source,d.access_state,d.last_error
            FROM (SELECT ? AS user_id) u
            LEFT JOIN test_subscriptions s ON s.user_id=u.user_id
            LEFT JOIN subscription_sources ss ON ss.user_id=u.user_id
            LEFT JOIN vpn_devices d ON d.user_id=u.user_id""", (user_id,)).fetchone()
        vpn = 'none' if row[3] is None else ('unknown' if row[4] else row[3])
        return {'subscription': {'started_at': row[0], 'expires_at': row[1]} if row[0] is not None else None,
                'source': (row[2] or 'unknown') if row[0] is not None else 'unknown', 'vpn': vpn}


def update_subscription_source(connection, user_id, source, active):
    row = connection.execute('SELECT source FROM subscription_sources WHERE user_id=?', (user_id,)).fetchone()
    if active:
        previous = row[0] if row else 'unknown'
        source = previous if previous in (source, 'unknown', 'mixed') else 'mixed'
    connection.execute('INSERT INTO subscription_sources VALUES (?,?) ON CONFLICT(user_id) DO UPDATE SET source=excluded.source', (user_id, source))


def record_entitlement(connection, user_id, kind, charge_id, current, seconds, previous, started, expiry):
    state = connection.execute('SELECT complete,expected_start,expected_end FROM subscription_ledger_state WHERE user_id=?', (user_id,)).fetchone()
    complete = not previous if state is None else bool(state[0]) and (state[1], state[2]) == (tuple(previous) if previous is not None else (None, None))
    last = connection.execute('SELECT occurred_at FROM subscription_ledger WHERE user_id=? ORDER BY id DESC LIMIT 1', (user_id,)).fetchone()
    if last and current < last[0]: complete = False
    connection.execute('INSERT INTO subscription_ledger(user_id,kind,charge_id,occurred_at,seconds) VALUES(?,?,?,?,?)', (user_id,kind,charge_id,current,seconds))
    connection.execute('INSERT INTO subscription_ledger_state VALUES(?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET complete=excluded.complete,expected_start=excluded.expected_start,expected_end=excluded.expected_end', (user_id,int(complete),started,expiry))


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
            record_entitlement(connection, user_id, 'test', None, current, days * 86400, row, started_at, expires_at)
            update_subscription_source(connection, user_id, 'test', active)
            connection.commit()
            return {"started_at": started_at, "expires_at": expires_at}
        except Exception:
            connection.rollback()
            raise
