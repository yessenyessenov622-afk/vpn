"""Проверка подписанных данных Telegram Mini App."""
import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl


class AuthError(ValueError):
    pass


def validate_init_data(raw: str, token: str, *, now: int | None = None, max_age: int = 86400) -> dict:
    if not raw or len(raw) > 16384 or not token:
        raise AuthError("Invalid authorization data")
    try:
        pairs = parse_qsl(raw, keep_blank_values=True, strict_parsing=True, max_num_fields=100)
        data = dict(pairs)
        if len(data) != len(pairs):
            raise ValueError("Duplicate fields")
        received_hash = data.pop("hash")
        check_string = "\n".join(f"{key}={value}" for key, value in sorted(data.items()))
        secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
        expected_hash = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected_hash, received_hash):
            raise ValueError("Invalid signature")
        auth_date = int(data["auth_date"])
        current = int(time.time()) if now is None else now
        if auth_date > current + 30 or current - auth_date > max_age:
            raise ValueError("Expired authorization")
        user = json.loads(data["user"])
        if not isinstance(user, dict) or type(user.get("id")) is not int or user["id"] <= 0:
            raise ValueError("Invalid user")
        return user
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise AuthError("Invalid or expired authorization data") from exc
