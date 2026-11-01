"""Reconcile managed devices with UTC subscriptions, under SQLite write lock."""
import ipaddress
import time
from contextlib import closing

from app import vpn_devices, vpn_alerts


def reconcile_one(user_id, controller, *, path=None, clock=time.time):
    with closing(vpn_devices._connect(path)) as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('''SELECT d.public_key, d.vpn_ip, d.server_id, d.access_state, s.expires_at
            FROM vpn_devices d LEFT JOIN test_subscriptions s ON s.user_id=d.user_id
            WHERE d.user_id=?''', (user_id,)).fetchone()
        if row is None or row['server_id'] != 'primary' or not row['vpn_ip']:
            db.commit()
            return 'skipped'
        key, address, expiry = row['public_key'], row['vpn_ip'], row['expires_at']
        active = expiry is not None and expiry > int(clock())
        action = ('restore' if row['access_state'] == 'revoked' else 'check') if active else 'revoke'
        code = 'controller_error'
        try:
            if controller.is_owned(key, address) is not True:
                raise ValueError('unmanaged')
            peers = controller.list_peers()
            if peers.get(key) not in (None, address):
                code = 'conflict'
                raise ValueError('key conflict')
            wanted = ipaddress.ip_network(address, strict=True)
            if any(k != key and wanted.overlaps(ipaddress.ip_network(v, strict=False)) for k, v in peers.items()):
                code = 'conflict'
                raise ValueError('address conflict')
            if active:
                if key not in peers:
                    action = 'restore'
                if key not in peers and controller.add_if_free(key, address, expiry) is not True:
                    code = 'unconfirmed'
                    raise RuntimeError('unconfirmed')
                if controller.list_peers().get(key) != address or expiry <= int(clock()):
                    code = 'unconfirmed'
                    raise RuntimeError('unconfirmed or expired')
                state = 'allowed'
            else:
                if controller.remove_if_owned(key, address) is not True:
                    code = 'unconfirmed'
                    raise RuntimeError('unconfirmed')
                if key in controller.list_peers():
                    code = 'unconfirmed'
                    raise RuntimeError('unconfirmed')
                state = 'revoked'
            db.execute("UPDATE vpn_devices SET access_state=?, last_error=NULL, updated_at=? WHERE user_id=?", (state, int(clock()), user_id))
            vpn_alerts.resolve(db, user_id, int(clock()))
            db.commit()
            return state
        except Exception:
            db.execute("UPDATE vpn_devices SET last_error='confirmation_lost', updated_at=? WHERE user_id=?", (int(clock()), user_id))
            vpn_alerts.report(db, user_id, action, code, int(clock()))
            db.commit()
            return 'error'


def reconcile_all(controller, *, path=None, clock=time.time):
    with closing(vpn_devices._connect(path)) as db:
        ids = [r[0] for r in db.execute("SELECT user_id FROM vpn_devices WHERE server_id='primary' AND vpn_ip IS NOT NULL")]
    return [reconcile_one(user_id, controller, path=path, clock=clock) for user_id in ids]
