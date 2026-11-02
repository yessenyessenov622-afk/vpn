"""Local refund state machine. It never calls Telegram or a VPN controller."""
import time
from contextlib import closing
from app import vpn_alerts, vpn_devices


def _time(now):
    return int(time.time()) if now is None else now


def prepare(admin_id, configured_admin, user_id, charge_id, *, path=None, now=None):
    if type(admin_id) is not int or type(configured_admin) is not int or configured_admin <= 0 or admin_id != configured_admin:
        raise ValueError('administrator required')
    if type(user_id) is not int or user_id <= 0 or not isinstance(charge_id, str) or not 1 <= len(charge_id) <= 255:
        raise ValueError('invalid refund')
    with closing(vpn_devices._connect(path)) as db:
        with db:
            payment = db.execute('SELECT user_id,currency FROM payments WHERE charge_id=?', (charge_id,)).fetchone()
            if not payment or payment['user_id'] != user_id or payment['currency'] != 'XTR':
                raise ValueError('payment or owner mismatch')
            db.execute("INSERT OR IGNORE INTO star_refunds(charge_id,user_id,status,updated_at) VALUES(?,?,'prepared',?)", (charge_id,user_id,_time(now)))
            return dict(db.execute('SELECT status,recalc_status FROM star_refunds WHERE charge_id=?', (charge_id,)).fetchone())


def begin_attempt(charge_id, *, path=None, now=None):
    """Persist uncertainty before a hypothetical API call; never retry automatically."""
    with closing(vpn_devices._connect(path)) as db:
        with db:
            changed = db.execute("UPDATE star_refunds SET status='uncertain',updated_at=? WHERE charge_id=? AND status='prepared'", (_time(now),charge_id)).rowcount
            return bool(changed)


def begin_authorized(admin_id, configured_admin, user_id, charge_id, *, path=None, now=None):
    if type(admin_id) is not int or type(configured_admin) is not int or configured_admin <= 0 or admin_id != configured_admin:
        raise ValueError('administrator required')
    with closing(vpn_devices._connect(path)) as db:
        db.execute('BEGIN IMMEDIATE')
        try:
            row = db.execute('''SELECT r.status,p.user_id,p.amount,p.currency FROM star_refunds r
                JOIN payments p ON p.charge_id=r.charge_id WHERE r.charge_id=? AND r.user_id=? AND p.user_id=?''',
                (charge_id,user_id,user_id)).fetchone()
            if not row: raise ValueError('payment or owner mismatch')
            if row['status'] != 'prepared':
                db.commit()
                return {'status':row['status']}
            db.execute("UPDATE star_refunds SET status='uncertain',updated_at=? WHERE charge_id=?", (_time(now),charge_id))
            db.commit()
            return {'status':'uncertain','amount':row['amount'],'currency':row['currency'],'ready':True}
        except Exception:
            db.rollback()
            raise


def reject_attempt(charge_id, *, path=None, now=None):
    """An explicit Telegram refusal, not a network exception."""
    with closing(vpn_devices._connect(path)) as db:
        with db:
            return bool(db.execute("UPDATE star_refunds SET status='rejected',updated_at=? WHERE charge_id=? AND status='uncertain'", (_time(now),charge_id)).rowcount)


def attempt_for_test(charge_id, invoke, *, path=None, now=None):
    """Exercise the state machine with an injected fake; never wired to Telegram."""
    if not begin_attempt(charge_id, path=path, now=now):
        return 'already_processed'
    with closing(vpn_devices._connect(path)) as db:
        payment = db.execute('SELECT user_id,amount,currency FROM payments WHERE charge_id=?', (charge_id,)).fetchone()
    try:
        answer = invoke(payment['user_id'], charge_id)
    except Exception:
        return 'uncertain'
    if answer is False:
        reject_attempt(charge_id, path=path, now=now)
        return 'rejected'
    if answer is not True:
        return 'uncertain'
    return confirm(charge_id, payment['user_id'], payment['amount'], payment['currency'], path=path, now=now)


def confirm(charge_id, user_id, amount, currency, *, order_id=None, path=None, now=None):
    """Confirm verified history/API result and atomically recalculate when evidence is complete."""
    current = _time(now)
    with closing(vpn_devices._connect(path)) as db:
        db.execute('BEGIN IMMEDIATE')
        try:
            if order_id is not None:
                db.execute("INSERT OR IGNORE INTO refund_observations VALUES(?,?,?,?,?,'review')", (charge_id,user_id,amount,currency,order_id))
            payment = db.execute('SELECT * FROM payments WHERE charge_id=?', (charge_id,)).fetchone()
            if not payment or (payment['user_id'],payment['amount'],payment['currency']) != (user_id,amount,currency) or (order_id is not None and payment['order_id'] != order_id):
                vpn_alerts.report(db, user_id if type(user_id) is int and user_id > 0 else 0, 'history', 'manual_review', current)
                db.commit()
                return 'review'
            previous = db.execute('SELECT * FROM star_refunds WHERE charge_id=?', (charge_id,)).fetchone()
            if previous and previous['status'] == 'confirmed':
                if order_id is not None:
                    db.execute("UPDATE refund_observations SET status=? WHERE charge_id=? AND user_id=? AND amount=? AND currency=? AND order_id=?", (previous['recalc_status'],charge_id,user_id,amount,currency,order_id))
                db.commit()
                return previous['recalc_status']
            db.execute("INSERT INTO star_refunds(charge_id,user_id,status,updated_at) VALUES(?,?,'confirmed',?) ON CONFLICT(charge_id) DO UPDATE SET status='confirmed',updated_at=excluded.updated_at", (charge_id,user_id,current))
            state = db.execute('SELECT * FROM subscription_ledger_state WHERE user_id=?', (user_id,)).fetchone()
            sub = db.execute('SELECT started_at,expires_at FROM test_subscriptions WHERE user_id=?', (user_id,)).fetchone()
            event = db.execute("SELECT 1 FROM subscription_ledger WHERE user_id=? AND charge_id=? AND kind='paid'", (user_id,charge_id)).fetchone()
            complete = state and state['complete'] and sub and (state['expected_start'],state['expected_end']) == (sub['started_at'],sub['expires_at']) and event
            if not complete:
                db.execute("UPDATE star_refunds SET recalc_status='manual_review' WHERE charge_id=?", (charge_id,))
                vpn_alerts.report(db, user_id, 'history', 'manual_review', current)
                if order_id is not None:
                    db.execute("UPDATE refund_observations SET status='manual_review' WHERE charge_id=? AND user_id=? AND amount=? AND currency=? AND order_id=?", (charge_id,user_id,amount,currency,order_id))
                db.commit()
                return 'manual_review'
            events = db.execute("""SELECT l.* FROM subscription_ledger l LEFT JOIN star_refunds r ON r.charge_id=l.charge_id AND r.status='confirmed'
                WHERE l.user_id=? AND r.charge_id IS NULL ORDER BY l.id""", (user_id,)).fetchall()
            started = expiry = None
            sources = set()
            for item in events:
                if expiry is None or expiry <= item['occurred_at']:
                    started, expiry, sources = item['occurred_at'], item['occurred_at'], set()
                expiry += item['seconds']
                sources.add(item['kind'])
            if expiry is None:
                started = expiry = current
            source = 'mixed' if len(sources) > 1 else next(iter(sources), 'unknown')
            db.execute('UPDATE test_subscriptions SET started_at=?,expires_at=? WHERE user_id=?', (started,expiry,user_id))
            db.execute('UPDATE subscription_ledger_state SET expected_start=?,expected_end=? WHERE user_id=?', (started,expiry,user_id))
            db.execute('INSERT INTO subscription_sources VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET source=excluded.source', (user_id,source))
            db.execute("UPDATE star_refunds SET recalc_status='applied' WHERE charge_id=?", (charge_id,))
            if order_id is not None:
                db.execute("UPDATE refund_observations SET status='applied' WHERE charge_id=? AND user_id=? AND amount=? AND currency=? AND order_id=?", (charge_id,user_id,amount,currency,order_id))
            db.commit()
            return 'applied'
        except Exception:
            db.rollback()
            raise
