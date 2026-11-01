#!/usr/bin/python3
"""Root-owned, fixed-operation WireGuard helper for wg0. Never print secrets."""
import base64
import fcntl
import ipaddress
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

CONFIG = Path('/etc/wireguard/wg0.conf')
STATE = Path('/var/lib/telegram-vpn-controller')
ENDPOINT = Path('/etc/telegram-vpn-controller/endpoint')
WG = '/usr/bin/wg'
NETWORK = ipaddress.ip_network('10.77.0.0/24')


def key(value):
    if not isinstance(value, str) or len(value) != 44:
        raise ValueError('invalid key')
    raw = base64.b64decode(value, validate=True)
    if len(raw) != 32 or base64.b64encode(raw).decode() != value:
        raise ValueError('invalid key')
    return value


def address(value):
    net = ipaddress.ip_network(value, strict=True)
    if net.version != 4 or net.prefixlen != 32 or net.network_address not in NETWORK:
        raise ValueError('invalid address')
    if int(net.network_address) in (int(NETWORK.network_address), int(NETWORK.network_address)+1, int(NETWORK.network_address)+2, int(NETWORK.broadcast_address)):
        raise ValueError('reserved address')
    return str(net)


def wg(*args):
    return subprocess.run([WG, *args], check=True, stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL, text=True, timeout=10).stdout.strip()


def live_peers():
    result = {}
    for line in wg('show', 'wg0', 'allowed-ips').splitlines():
        parts = line.split()
        if len(parts) != 2 or ',' in parts[1]:
            raise ValueError('unsupported live peer')
        k = key(parts[0])
        net = str(ipaddress.ip_network(parts[1], strict=True))
        if k in result:
            raise ValueError('duplicate peer')
        result[k] = net
    return result


def configured_peers(text):
    result = {}
    section = None
    fields = {}
    def finish():
        if section == 'peer':
            k = key(fields['publickey'])
            net = str(ipaddress.ip_network(fields['allowedips'], strict=True))
            if k in result:
                raise ValueError('duplicate peer')
            result[k] = net
    for line in text.splitlines():
        line = line.split('#', 1)[0].strip()
        if not line:
            continue
        if line.startswith('[') and line.endswith(']'):
            finish()
            section = line[1:-1].lower()
            if section not in ('interface', 'peer'):
                raise ValueError('invalid section')
            fields = {}
            continue
        if '=' not in line:
            raise ValueError('invalid configuration')
        name, value = (part.strip() for part in line.split('=', 1))
        name = name.lower()
        if section == 'interface' and name == 'saveconfig' and value.lower() not in ('false', 'no', 'off', '0'):
            raise ValueError('SaveConfig must be disabled')
        if section == 'peer' and name in ('publickey', 'allowedips'):
            if name in fields:
                raise ValueError('duplicate field')
            fields[name] = value
    finish()
    return result


def atomic_write(path, data, mode):
    fd, name = tempfile.mkstemp(prefix='.vpn-', dir=str(path.parent))
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        directory = os.open(str(path.parent), os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def overlaps(peers, k, a):
    wanted = ipaddress.ip_network(a)
    return any(other != k and wanted.overlaps(ipaddress.ip_network(net)) for other, net in peers.items())


def registry():
    path = STATE / 'managed.json'
    data = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    if not isinstance(data, dict):
        raise ValueError('invalid registry')
    return {key(k): address(v) for k, v in data.items()}


def register(k, a):
    managed = registry()
    if managed.get(k) not in (None, a) or overlaps(managed, k, a):
        raise ValueError('registry conflict')
    managed[k] = a
    atomic_write(STATE / 'managed.json', json.dumps(managed, sort_keys=True), 0o600)


def remove_saved_peer(text, k, a):
    # Only remove the exact section created by this helper, never arbitrary sections.
    block = '\n\n[Peer]\nPublicKey = ' + k + '\nAllowedIPs = ' + a + '\n'
    if text.count(block) != 1:
        raise ValueError('managed section changed')
    return text.replace(block, '\n', 1)


def recover():
    journal = STATE / 'pending.json'
    if not journal.exists():
        return
    pending = json.loads(journal.read_text(encoding='utf-8'))
    k, a = key(pending['key']), address(pending['address'])
    operation = pending.get('operation', 'add')
    if operation not in ('add', 'remove') or registry().get(k) != a:
        raise ValueError('unmanaged pending operation')
    text = CONFIG.read_text(encoding='utf-8')
    saved, live = configured_peers(text), live_peers()
    if overlaps(saved, k, a) or overlaps(live, k, a) or saved.get(k) not in (None, a) or live.get(k) not in (None, a):
        raise ValueError('pending conflict')
    if operation == 'remove':
        if k in saved:
            atomic_write(CONFIG, remove_saved_peer(text, k, a), 0o600)
        if k in live:
            wg('set', 'wg0', 'peer', k, 'remove')
        if k in configured_peers(CONFIG.read_text(encoding='utf-8')) or k in live_peers():
            raise ValueError('removal unconfirmed')
        journal.unlink()
        return
    if live.get(k) == a and k not in saved:
        atomic_write(CONFIG, text.rstrip() + '\n\n[Peer]\nPublicKey = ' + k + '\nAllowedIPs = ' + a + '\n', 0o600)
        saved = configured_peers(CONFIG.read_text(encoding='utf-8'))
    if k in saved and live.get(k) != a:
        raise ValueError('pending requires manual reconciliation')
    if k in saved and saved[k] != a:
        raise ValueError('pending mismatch')
    journal.unlink()


def checked_peers():
    recover()
    live = live_peers()
    saved = configured_peers(CONFIG.read_text(encoding='utf-8'))
    if live != saved:
        raise ValueError('live and saved peers differ')
    return live


def execute(request):
    if not isinstance(request, dict) or set(request) - {'operation', 'key', 'address', 'expires_at'}:
        raise ValueError('invalid request')
    op = request.get('operation')
    peers = checked_peers()
    if op == 'list' and set(request) == {'operation'}:
        return {'peers': peers}
    if op == 'details' and set(request) == {'operation'}:
        host = str(ipaddress.ip_address(ENDPOINT.read_text(encoding='ascii').strip()))
        port = int(wg('show', 'wg0', 'listen-port'))
        if not 1 <= port <= 65535 or ':' in host:
            raise ValueError('invalid endpoint')
        return {'public_key': key(wg('show', 'wg0', 'public-key')), 'endpoint': host + ':' + str(port)}
    if op == 'owned' and set(request) == {'operation', 'key', 'address'}:
        k, a = key(request['key']), address(request['address'])
        return {'owned': registry().get(k) == a}
    if op == 'remove' and set(request) == {'operation', 'key', 'address'}:
        k, a = key(request['key']), address(request['address'])
        if registry().get(k) != a or peers.get(k) not in (None, a) or overlaps(peers, k, a):
            raise ValueError('unmanaged or conflicting peer')
        if k not in peers:
            return {'confirmed': True}
        # Validate the exact on-disk section before changing anything.
        remove_saved_peer(CONFIG.read_text(encoding='utf-8'), k, a)
        atomic_write(STATE / 'pending.json', json.dumps({'operation': 'remove', 'key': k, 'address': a}), 0o600)
        recover()
        if k in checked_peers():
            raise ValueError('removal unconfirmed')
        return {'confirmed': True}
    if op != 'add' or set(request) != {'operation', 'key', 'address', 'expires_at'}:
        raise ValueError('invalid operation')
    k, a, expiry = key(request['key']), address(request['address']), request['expires_at']
    if type(expiry) is not int or expiry <= int(time.time()):
        raise ValueError('expired')
    if peers.get(k) == a and not overlaps(peers, k, a):
        if registry().get(k) != a:
            raise ValueError('unmanaged peer')
        return {'confirmed': True}
    if k in peers or overlaps(peers, k, a):
        raise ValueError('conflict')
    register(k, a)
    atomic_write(STATE / 'pending.json', json.dumps({'operation': 'add', 'key': k, 'address': a}), 0o600)
    if expiry <= int(time.time()):
        (STATE / 'pending.json').unlink()
        raise ValueError('expired')
    wg('set', 'wg0', 'peer', k, 'allowed-ips', a)
    recover()
    if checked_peers().get(k) != a:
        raise ValueError('not confirmed')
    return {'confirmed': True}


def main():
    if len(sys.argv) != 1:
        raise ValueError('arguments forbidden')
    raw = sys.stdin.buffer.read(4097)
    if len(raw) > 4096:
        raise ValueError('request too long')
    request = json.loads(raw)
    with (STATE / 'lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        result = execute(request)
    print(json.dumps({'ok': True, 'value': result}, separators=(',', ':')))


if __name__ == '__main__':
    try:
        main()
    except Exception:
        print('{"ok":false}')
        sys.exit(1)
