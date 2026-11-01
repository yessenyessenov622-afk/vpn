"""Durable, secret-free notification state. All times are UTC Unix seconds."""
from contextlib import closing
import time
from app import vpn_devices

INTERVAL = 3600
VALID_ACTIONS = {'check', 'revoke', 'restore', 'enable', 'scan'}
VALID_CODES = {'controller_error', 'unconfirmed', 'conflict', 'scan_error'}


def report(db, user_id, action, code, now):
    if action not in VALID_ACTIONS or code not in VALID_CODES:
        raise ValueError('invalid alert')
    db.execute('''INSERT INTO vpn_alerts(user_id,action,code,active,occurred_at,version)
      VALUES(?,?,?,1,?,1) ON CONFLICT(user_id,action,code) DO UPDATE SET
      occurred_at=CASE WHEN vpn_alerts.active=0 THEN excluded.occurred_at ELSE vpn_alerts.occurred_at END,
      last_sent=CASE WHEN vpn_alerts.active=0 THEN NULL ELSE vpn_alerts.last_sent END,
      notified=CASE WHEN vpn_alerts.active=0 THEN 0 ELSE vpn_alerts.notified END,
      version=CASE WHEN vpn_alerts.active=0 THEN vpn_alerts.version+1 ELSE vpn_alerts.version END,
      active=1''', (user_id, action, code, now))


def resolve(db, user_id, now):
    db.execute('''UPDATE vpn_alerts SET active=0, resolved_at=?, version=version+1
                  WHERE user_id=? AND active=1''', (now, user_id))


def due(*, path=None, now=None):
    current = int(time.time()) if now is None else now
    with closing(vpn_devices._connect(path)) as db:
        rows = db.execute('''SELECT user_id,action,code,active,occurred_at,resolved_at,version,
            CASE WHEN active=0 AND notified=1 THEN 'resolved' ELSE 'failure' END AS phase
            FROM vpn_alerts WHERE (active=1 AND (last_sent IS NULL OR last_sent<=?))
            OR (active=0 AND (notified=1 OR last_sent IS NULL)) ORDER BY occurred_at,user_id LIMIT 100''', (current-INTERVAL,)).fetchall()
        return [dict(row) for row in rows]


def acknowledge(event, *, path=None, now=None):
    current = int(time.time()) if now is None else now
    if not isinstance(event, dict) or type(event.get('user_id')) is not int or event.get('action') not in VALID_ACTIONS or event.get('code') not in VALID_CODES or type(event.get('version')) is not int or type(event.get('active')) is not int or event['active'] not in (0, 1) or event.get('phase') not in ('failure', 'resolved') or (event['active'] == 1 and event['phase'] != 'failure'):
        raise ValueError('invalid alert acknowledgement')
    with closing(vpn_devices._connect(path)) as db:
        with db:
            db.execute('''UPDATE vpn_alerts SET last_sent=?, notified=? WHERE user_id=? AND action=? AND code=? AND active=? AND version=?''',
                (current, int(event['phase'] == 'failure'), event['user_id'], event['action'], event['code'], event['active'], event['version']))
