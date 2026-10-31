"""Дочерний процесс: по одной JSON-команде и одному ответу на строку."""
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app import database, vpn_provision

LANGUAGES = {"kk", "ru", "en", "tr", "uz", "ky", "de", "es"}


def execute(command, path=None):
    if path is None:
        path = database.DATABASE_PATH
    if not isinstance(command, dict):
        raise ValueError("Invalid request")
    user_id = command.get("user_id")
    if type(user_id) is not int or not 0 < user_id <= (1 << 52):
        raise ValueError("Invalid user")
    action = command.get("action")
    if action == "get":
        language = database.get_language(user_id, path)
        return language if language in LANGUAGES else None
    if action == "set" and command.get("language") in LANGUAGES:
        database.save_language(user_id, command["language"], path)
        return command["language"]
    if action == "register":
        database.register_user(user_id, path)
        return True
    if action == "subscription":
        return database.get_subscription(user_id, path)
    if action == "grant":
        return database.grant_subscription(user_id, command.get("days"), path)
    if action == "vpn_request":
        # Реальный контроллер не настроен; не используем AWS-доступ инструмента.
        return vpn_provision.request_access(user_id, command.get("public_key"), path=path)
    raise ValueError("Invalid action or language")


def main():
    database.initialize(database.DATABASE_PATH)
    if sys.argv[1:] == ["--check"]:
        print("Python и база SQLite готовы.")
        return
    if sys.argv[1:]:
        raise SystemExit("Использование: python storage/service.py [--check]")
    for line in sys.stdin:
        try:
            command = json.loads(line)
            value = execute(command)
            result = {"ok": True, "language": value} if command.get("action") in ("get", "set") else {"ok": True, "value": value}
        except (ValueError, TypeError, sqlite3.Error):
            result = {"ok": False}
        print(json.dumps(result, ensure_ascii=True), flush=True)


if __name__ == "__main__":
    main()
