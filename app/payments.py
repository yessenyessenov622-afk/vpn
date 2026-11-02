"""One-time Stars orders and atomic subscription fulfillment (UTC seconds)."""
import secrets
import sqlite3
import time
from contextlib import closing
from app import database, vpn_devices, vpn_alerts

PLAN_DAYS = {'days7': 7, 'days18': 18, 'days30': 30}


def create_order(user_id, plan_id, amount, *, path=None, now=None):
    user_id = vpn_devices._user_id(user_id)
    if plan_id not in PLAN_DAYS or type(amount) is not int or not 1 <= amount <= 1000000:
        raise ValueError('invalid plan or price')
    current = int(time.time()) if now is None else now
    order_id = secrets.token_urlsafe(24)
    with closing(vpn_devices._connect(path)) as db:
        with db:
            if not db.execute('SELECT 1 FROM registered_users WHERE user_id=?', (user_id,)).fetchone():
                raise ValueError('unknown user')
            db.execute('INSERT INTO payment_orders(order_id,user_id,plan_id,days,currency,amount,created_at) VALUES(?,?,?,?,?,?,?)',
                       (order_id,user_id,plan_id,PLAN_DAYS[plan_id],'XTR',amount,current))
    return {'order_id':order_id,'days':PLAN_DAYS[plan_id],'currency':'XTR','amount':amount}


def valid_order(user_id, order_id, currency, amount, *, path=None):
    if type(user_id) is not int or not isinstance(order_id,str) or currency != 'XTR' or type(amount) is not int:
        return False
    with closing(vpn_devices._connect(path)) as db:
        row = db.execute('SELECT user_id,currency,amount,status FROM payment_orders WHERE order_id=?', (order_id,)).fetchone()
        return bool(row and row['user_id']==user_id and row['currency']==currency and row['amount']==amount and row['status']=='pending')


def apply_payment(user_id, order_id, currency, amount, charge_id, *, path=None, now=None):
    if type(user_id) is not int or not isinstance(order_id,str) or currency != 'XTR' or type(amount) is not int or not isinstance(charge_id,str) or not 1 <= len(charge_id) <= 255:
        raise ValueError('invalid payment')
    current = int(time.time()) if now is None else now
    with closing(vpn_devices._connect(path)) as db:
        db.execute('BEGIN IMMEDIATE')
        try:
            old = db.execute('SELECT * FROM payments WHERE charge_id=?', (charge_id,)).fetchone()
            if old:
                if (old['user_id'],old['order_id'],old['currency'],old['amount']) != (user_id,order_id,currency,amount):
                    raise ValueError('charge conflict')
                db.commit()
                return {'status':'duplicate','started_at':old['started_at'],'expires_at':old['expires_at']}
            order = db.execute('SELECT * FROM payment_orders WHERE order_id=?', (order_id,)).fetchone()
            if not order or (order['user_id'],order['currency'],order['amount'],order['status']) != (user_id,currency,amount,'pending') or PLAN_DAYS.get(order['plan_id']) != order['days']:
                raise ValueError('order mismatch')
            sub = db.execute('SELECT started_at,expires_at FROM test_subscriptions WHERE user_id=?',(user_id,)).fetchone()
            active = sub is not None and sub['expires_at'] > current
            started = sub['started_at'] if active else current
            expiry = (sub['expires_at'] if active else current) + order['days']*86400
            if expiry > 253402300799: raise ValueError('expiration out of range')
            db.execute('INSERT INTO payments VALUES (?,?,?,?,?,?,?,?)',(charge_id,order_id,user_id,currency,amount,current,started,expiry))
            db.execute('UPDATE payment_orders SET status=? WHERE order_id=?',('paid',order_id))
            db.execute('INSERT INTO test_subscriptions(user_id,started_at,expires_at) VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET started_at=excluded.started_at,expires_at=excluded.expires_at',(user_id,started,expiry))
            database.record_entitlement(db, user_id, 'paid', charge_id, current, order['days']*86400, sub, started, expiry)
            database.update_subscription_source(db, user_id, 'paid', active)
            db.commit()
            return {'status':'paid','started_at':started,'expires_at':expiry}
        except Exception:
            db.rollback()
            raise


def accept_payment(user_id, order_id, currency, amount, charge_id, *, path=None, now=None):
    """Durably record receipt first; retries can resume after process restart."""
    if type(user_id) is not int or user_id <= 0 or not isinstance(order_id, str) or not order_id or currency != 'XTR' or type(amount) is not int or amount <= 0 or not isinstance(charge_id, str) or not 1 <= len(charge_id) <= 255:
        raise ValueError('invalid receipt')
    current = int(time.time()) if now is None else now
    with closing(vpn_devices._connect(path)) as db:
        with db:
            old = db.execute('SELECT * FROM payment_inbox WHERE charge_id=?', (charge_id,)).fetchone()
            if old and (old['user_id'],old['order_id'],old['currency'],old['amount']) != (user_id,order_id,currency,amount):
                raise ValueError('receipt conflict')
            if not old:
                db.execute('INSERT INTO payment_inbox(charge_id,user_id,order_id,currency,amount,received_at) VALUES(?,?,?,?,?,?)', (charge_id,user_id,order_id,currency,amount,current))
    return process_receipt(charge_id, path=path, now=current)


def process_receipt(charge_id, *, path=None, now=None):
    current = int(time.time()) if now is None else now
    with closing(vpn_devices._connect(path)) as db:
        row = db.execute('SELECT * FROM payment_inbox WHERE charge_id=?',(charge_id,)).fetchone()
        if not row: raise ValueError('unknown receipt')
        receipt = dict(row)
    try:
        result = apply_payment(receipt['user_id'],receipt['order_id'],receipt['currency'],receipt['amount'],charge_id,path=path,now=current)
    except Exception:
        with closing(vpn_devices._connect(path)) as db:
            with db: vpn_alerts.report(db,receipt['user_id'],'payment','fulfillment_error',current)
        return {'status':'pending'}
    with closing(vpn_devices._connect(path)) as db:
        with db:
            db.execute("UPDATE payment_inbox SET status='processed' WHERE charge_id=?",(charge_id,))
            db.execute("UPDATE vpn_alerts SET active=0,resolved_at=?,version=version+1 WHERE user_id=? AND action='payment' AND code='fulfillment_error' AND active=1",(current,receipt['user_id']))
    return result


def retry_pending(*, path=None, now=None):
    with closing(vpn_devices._connect(path)) as db:
        charges = [row[0] for row in db.execute("SELECT charge_id FROM payment_inbox WHERE status='pending' ORDER BY received_at")]
    return [process_receipt(charge,path=path,now=now) for charge in charges]
