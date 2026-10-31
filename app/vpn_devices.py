"""Хранение одного публичного VPN-устройства на пользователя.

Модуль не подключается к серверу. Состояние записывается только вызывающей
стороной, получившей явное подтверждение контроллера.
"""
import base64
import binascii
import sqlite3
import time
from contextlib import closing

from app import database, vpn_policy

# Только фиксированные коды: сообщения исключений могут содержать секреты.
ERROR_CODES = frozenset({"connection_error", "controller_rejected", "confirmation_lost", "internal_error"})


class DeviceError(ValueError):
    """Понятная ошибка пользовательских данных или состояния устройства."""


def _user_id(value):
    if type(value) is not int or not 0 < value <= 2**52:
        raise DeviceError("Укажите корректный положительный Telegram ID.")
    return value


def _public_key(value):
    if not isinstance(value, str):
        raise DeviceError("Некорректный формат публичного ключа WireGuard.")
    key = value.strip()
    try:
        raw = base64.b64decode(key, validate=True)
    except (ValueError, binascii.Error):
        raise DeviceError("Некорректный формат публичного ключа WireGuard.") from None
    if len(raw) != 32 or base64.b64encode(raw).decode("ascii") != key:
        raise DeviceError("Публичный ключ должен содержать 32 байта в формате Base64.")
    return key


def _now(value):
    current = int(time.time()) if value is None else value
    if type(current) is not int or current < 0:
        raise DeviceError("Время должно быть указано в UTC Unix-секундах.")
    return current


def _connect(path):
    connection = sqlite3.connect(database.DATABASE_PATH if path is None else path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def add_device(user_id, public_key, *, path=None, now=None):
    user_id, key, current = _user_id(user_id), _public_key(public_key), _now(now)
    with closing(_connect(path)) as connection:
        connection.execute("BEGIN IMMEDIATE")
        try:
            if not connection.execute("SELECT 1 FROM registered_users WHERE user_id = ?", (user_id,)).fetchone():
                raise DeviceError("Пользователь не зарегистрирован в боте.")
            if connection.execute("SELECT 1 FROM vpn_devices WHERE user_id = ?", (user_id,)).fetchone():
                raise DeviceError("У пользователя уже есть устройство; замена пока недоступна.")
            if connection.execute("SELECT 1 FROM vpn_devices WHERE public_key = ?", (key,)).fetchone():
                raise DeviceError("Этот публичный ключ уже принадлежит другому пользователю.")
            connection.execute("INSERT INTO vpn_devices (user_id, public_key, created_at, updated_at) VALUES (?, ?, ?, ?)", (user_id, key, current, current))
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    return get_device(user_id, path=path)


def get_device(user_id, *, path=None):
    with closing(_connect(path)) as connection:
        row = connection.execute("SELECT user_id, public_key, created_at, updated_at, access_state, last_error FROM vpn_devices WHERE user_id = ?", (_user_id(user_id),)).fetchone()
        return dict(row) if row else None


def save_confirmed_state(user_id, public_key, enabled, *, controller_confirmed, path=None, now=None):
    """Вызывать только после явного подтверждения реального контроллера.

    Флаг задаётся доверенным вызывающим кодом, который отвечает за получение
    подтверждения. В проекте пока нет реального вызывающего контроллера.
    """
    user_id, key, current = _user_id(user_id), _public_key(public_key), _now(now)
    if type(enabled) is not bool or controller_confirmed is not True:
        raise DeviceError("Для сохранения требуется подтверждённое состояние контроллера.")
    state = "allowed" if enabled else "revoked"
    with closing(_connect(path)) as connection:
        with connection:
            result = connection.execute("UPDATE vpn_devices SET access_state = ?, last_error = NULL, updated_at = ? WHERE user_id = ? AND public_key = ?", (state, current, user_id, key))
            if result.rowcount != 1:
                raise DeviceError("Устройство пользователя с этим ключом не найдено.")
    return get_device(user_id, path=path)


def record_error(user_id, public_key, error_code, *, path=None, now=None):
    user_id, key, current = _user_id(user_id), _public_key(public_key), _now(now)
    if not isinstance(error_code, str) or error_code not in ERROR_CODES:
        raise DeviceError("Неизвестный код ошибки контроллера.")
    with closing(_connect(path)) as connection:
        with connection:
            result = connection.execute("UPDATE vpn_devices SET last_error = ?, updated_at = ? WHERE user_id = ? AND public_key = ?", (error_code, current, user_id, key))
            if result.rowcount != 1:
                raise DeviceError("Устройство пользователя с этим ключом не найдено.")
    return get_device(user_id, path=path)


def list_devices_for_check(*, path=None):
    with closing(_connect(path)) as connection:
        rows = connection.execute("""SELECT d.user_id, d.public_key, d.created_at, d.updated_at,
            d.access_state, d.last_error, s.expires_at
            FROM vpn_devices AS d LEFT JOIN test_subscriptions AS s ON s.user_id = d.user_id
            ORDER BY d.user_id""").fetchall()
        return [dict(row) for row in rows]


def decide_for_device(record, *, now=None):
    """Подготовить решение без изменения базы и без подключения к VPN."""
    state = record["access_state"]
    if state not in ("unknown", "allowed", "revoked"):
        raise DeviceError("Неизвестное состояние устройства.")
    # После ошибки последнее подтверждение сохранено, но фактическое состояние
    # может отличаться: перед новым действием необходима проверка сервера.
    enabled = None if state == "unknown" or record["last_error"] else state == "allowed"
    device = vpn_policy.Device(user_id=record["user_id"], device_id=record["public_key"], prepared=True, access_enabled=enabled)
    expiry = record["expires_at"]
    subscription = vpn_policy.Subscription(user_id=record["user_id"], expires_at=expiry) if expiry is not None else None
    return vpn_policy.decide(device, subscription, now=now)
