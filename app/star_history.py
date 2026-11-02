"""Persist minimal observations; ambiguous transactions never grant access."""
import time
from contextlib import closing
from app import payments, refunds, vpn_alerts, vpn_devices


def observe(transaction, *, path=None, now=None):
    if not isinstance(transaction, dict): raise ValueError('invalid transaction')
    ident = transaction.get('id')
    direction = transaction.get('direction')
    user = transaction.get('user_id')
    order = transaction.get('order_id')
    amount = transaction.get('amount')
    date = transaction.get('date')
    refund_verified = transaction.get('refund_verified') is True and direction == 'outgoing'
    if not isinstance(ident,str) or not 1 <= len(ident) <= 255 or direction not in ('incoming','outgoing','unknown'):
        raise ValueError('invalid history identity')
    if user is not None and (type(user) is not int or not 0 < user <= 2**52): raise ValueError('invalid user')
    if order is not None and (not isinstance(order,str) or len(order) > 128): raise ValueError('invalid payload')
    if type(amount) is not int or type(date) is not int: raise ValueError('invalid history values')
    with closing(vpn_devices._connect(path)) as db:
        with db:
            existing = db.execute('SELECT * FROM star_history WHERE transaction_id=? AND direction=?',(ident,direction)).fetchone()
            if existing and (existing['user_id'],existing['order_id'],existing['amount'],existing['occurred_at']) != (user,order,amount,date):
                db.execute("UPDATE star_history SET status='review' WHERE transaction_id=? AND direction=?",(ident,direction))
                vpn_alerts.report(db,user or 0,'history','manual_review',int(time.time()) if now is None else now)
                return 'review'
            db.execute('INSERT OR IGNORE INTO star_history(transaction_id,direction,user_id,order_id,amount,occurred_at,refund_verified) VALUES(?,?,?,?,?,?,?)',(ident,direction,user,order,amount,date,int(refund_verified)))
            if refund_verified:
                db.execute('UPDATE star_history SET refund_verified=1 WHERE transaction_id=? AND direction=?',(ident,direction))
    return 'observed'


def finalize(*, path=None, now=None):
    current = int(time.time()) if now is None else now
    with closing(vpn_devices._connect(path)) as db:
        with db:
            db.execute("""UPDATE star_history SET status='processed' WHERE status='pending'
                AND direction='incoming' AND EXISTS(SELECT 1 FROM payment_inbox p
                WHERE p.charge_id=star_history.transaction_id AND p.status='processed')""")
        rows = [dict(r) for r in db.execute("SELECT * FROM star_history WHERE status='observed' OR (status='refund_review' AND direction='outgoing') ORDER BY occurred_at, transaction_id")]
    for row in rows:
        ident,user,order,amount = row['transaction_id'],row['user_id'],row['order_id'],row['amount']
        with closing(vpn_devices._connect(path)) as db:
            refund = bool(db.execute("SELECT 1 FROM star_history WHERE transaction_id=? AND direction='outgoing'",(ident,)).fetchone())
            paid = db.execute('SELECT * FROM payments WHERE charge_id=?',(ident,)).fetchone()
        if row['direction']=='outgoing':
            if row['refund_verified'] and paid and (paid['user_id'],paid['amount'],paid['currency']) == (user,amount,'XTR'):
                result = refunds.confirm(ident,user,amount,'XTR',path=path,now=current)
                state = 'refund_processed' if result == 'applied' else 'refund_review'
            else:
                state = 'refund_review'
        elif refund:
            state = 'review'
        elif paid:
            state = 'processed' if (paid['user_id'],paid['order_id'],paid['amount'],paid['currency']) == (user,order,amount,'XTR') else 'review'
        elif user and order and amount > 0 and payments.valid_order(user,order,'XTR',amount,path=path):
            result = payments.accept_payment(user,order,'XTR',amount,ident,path=path,now=current)
            state = 'processed' if result['status'] in ('paid','duplicate') else 'pending'
        else:
            state = 'review'
        with closing(vpn_devices._connect(path)) as db:
            with db:
                db.execute('UPDATE star_history SET status=? WHERE transaction_id=? AND direction=? AND status=?',(state,ident,row['direction'],row['status']))
                if state in ('review','refund_review'):
                    vpn_alerts.report(db,user or 0,'history','manual_review',current)
