"""Проверка подписки и подготовка выдачи VPN.

Контроллер должен проверять адрес и ключ на сервере под общей блокировкой,
проверять срок подписки и возвращать подтверждение только после сохранения
конфигурации и проверки действующего интерфейса. Тестовая имитация находится
только в tests/. Если контроллер не передан, никаких устройств не создаём.
"""
import ipaddress
import sqlite3
import time
from contextlib import closing

from app import vpn_devices, vpn_policy, vpn_alerts

POOL = ipaddress.ip_network("10.77.0.0/24")
SERVER_ID = "primary"


def request_access(user_id, public_key, *, controller=None, path=None, clock=time.time):
    """Возвращает статус; секретные данные и сообщения исключений не выводит."""
    try:
        user_id = vpn_devices._user_id(user_id)
        key = vpn_devices._public_key(public_key)
    except vpn_devices.DeviceError:
        return {"status": "invalid_key"}

    with closing(vpn_devices._connect(path)) as db:
        # Блокирует другие операции выделения и изменения подписки в этой базе.
        db.execute("BEGIN IMMEDIATE")
        try:
            if not db.execute("SELECT 1 FROM registered_users WHERE user_id = ?", (user_id,)).fetchone():
                db.rollback()
                return {"status": "inactive"}
            subscription = db.execute("SELECT expires_at FROM test_subscriptions WHERE user_id = ?", (user_id,)).fetchone()
            now = int(clock())
            if subscription is None or subscription[0] <= now:
                db.rollback()
                return {"status": "inactive"}
            existing = db.execute("SELECT * FROM vpn_devices WHERE user_id = ?", (user_id,)).fetchone()
            if existing is not None and existing["public_key"] != key:
                db.rollback()
                return {"status": "device_exists"}
            if db.execute("SELECT 1 FROM vpn_devices WHERE public_key = ? AND user_id != ?", (key, user_id)).fetchone():
                db.rollback()
                return {"status": "key_in_use"}
            if controller is None:
                db.rollback()
                return {"status": "unavailable"}
            # Ошибки проверки не интерпретируем как разрешение доступа.
            try:
                peers = controller.list_peers()
                details = controller.server_details()
                if not isinstance(peers, dict) or not isinstance(details, dict):
                    raise ValueError("invalid controller response")
                occupied = []
                for address in peers.values():
                    net = ipaddress.ip_network(address, strict=False)
                    if net.version != 4:
                        raise ValueError("unsupported address")
                    occupied.append(net)
                server_key = vpn_devices._public_key(details["public_key"])
                endpoint = details["endpoint"]
                if not isinstance(endpoint, str) or not endpoint or len(endpoint) > 255 or any(c.isspace() for c in endpoint):
                    raise ValueError("invalid endpoint")
            except Exception:
                vpn_alerts.report(db, user_id, 'check', 'controller_error', int(clock()))
                db.commit()
                return {"status": "unavailable"}

            previous_ip = existing["vpn_ip"] if existing else None
            if existing and existing["server_id"] != SERVER_ID:
                db.rollback()
                return {"status": "device_exists"}
            if key in peers and (not previous_ip or peers[key] != previous_ip):
                # Не присваиваем найденный на сервере чужой peer по одному ключу.
                db.rollback()
                return {"status": "key_in_use"}
            reserved = {row[0] for row in db.execute("SELECT vpn_ip FROM vpn_devices WHERE server_id = ? AND vpn_ip IS NOT NULL", (SERVER_ID,))}
            if previous_ip:
                address = previous_ip
                if any(ipaddress.ip_interface(address).ip in net for peer, raw in peers.items() if peer != key for net in [ipaddress.ip_network(raw, strict=False)]):
                    db.rollback()
                    return {"status": "ip_in_use"}
            else:
                address = next((f"{ip}/32" for ip in POOL.hosts() if int(ip) != int(POOL.network_address) + 1 and f"{ip}/32" not in reserved and not any(ip in net for net in occupied)), None)
                if address is None:
                    db.rollback()
                    return {"status": "ip_in_use"}
                if existing:
                    db.execute("UPDATE vpn_devices SET vpn_ip = ?, server_id = ?, updated_at = ? WHERE user_id = ?", (address, SERVER_ID, now, user_id))
                else:
                    db.execute("INSERT INTO vpn_devices(user_id,public_key,created_at,updated_at,vpn_ip,server_id) VALUES(?,?,?,?,?,?)", (user_id, key, now, now, address, SERVER_ID))

            # Сохраняем назначение до обращения к серверу. Если процесс завершится
            # после изменения WireGuard, повторный запрос сможет сверить тот же
            # ключ и адрес, а другой пользователь не получит этот адрес.
            db.commit()
            db.execute("BEGIN IMMEDIATE")
            # Повторно проверяем срок перед возможной выдачей.
            expiry = db.execute("SELECT expires_at FROM test_subscriptions WHERE user_id = ?", (user_id,)).fetchone()[0]
            if expiry <= int(clock()):
                db.commit()
                return {"status": "inactive"}
            device = vpn_policy.Device(user_id=user_id, device_id=key, prepared=True, access_enabled=key in peers)
            action = vpn_policy.decide(device, vpn_policy.Subscription(user_id=user_id, expires_at=expiry), now=int(clock())).action
            error_code = 'controller_error'
            try:
                if action is vpn_policy.Action.ENABLE:
                    # Операция должна быть идемпотентной и атомарно проверять
                    # отсутствие конфликта непосредственно на сервере.
                    if controller.add_if_free(key, address, expiry) is not True:
                        error_code = 'unconfirmed'
                        raise RuntimeError("unconfirmed")
                if controller.list_peers().get(key) != address or expiry <= int(clock()):
                    error_code = 'unconfirmed'
                    raise RuntimeError("unconfirmed or expired")
            except Exception:
                error_time = int(clock())
                db.execute("UPDATE vpn_devices SET last_error = 'confirmation_lost', updated_at = ? WHERE user_id = ?", (error_time, user_id))
                vpn_alerts.report(db, user_id, 'enable', error_code, error_time)
                db.commit()
                return {"status": "unconfirmed"}
            confirmed_time = int(clock())
            db.execute("UPDATE vpn_devices SET access_state = 'allowed', last_error = NULL, updated_at = ? WHERE user_id = ?", (confirmed_time, user_id))
            vpn_alerts.resolve(db, user_id, confirmed_time)
            db.commit()
            return {"status": "confirmed", "address": address, "server_public_key": server_key, "endpoint": endpoint}
        except (sqlite3.Error, ValueError, KeyError):
            db.rollback()
            return {"status": "unavailable"}
