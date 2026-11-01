"""Дочерний процесс: по одной JSON-команде и одному ответу на строку."""
import json
import os
import sqlite3
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app import database, vpn_provision, vpn_alerts, vpn_devices

LANGUAGES = {"kk", "ru", "en", "tr", "uz", "ky", "de", "es"}


def execute(command, path=None):
    if path is None:
        path = database.DATABASE_PATH
    if not isinstance(command, dict):
        raise ValueError("Invalid request")
    if command.get("action") == "alerts_due":
        return vpn_alerts.due(path=path)
    if command.get("action") == "alerts_ack":
        vpn_alerts.acknowledge(command.get("event"), path=path)
        return True
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
        # Опционально включается только на сервере после установки ограниченного helper.
        controller = None
        if os.environ.get("VPN_LOCAL_CONTROLLER") == "1":
            from app.wg_controller import LocalWireGuardController
            controller = LocalWireGuardController()
        return vpn_provision.request_access(user_id, command.get("public_key"), controller=controller, path=path)
    raise ValueError("Invalid action or language")


def main():
    database.initialize(database.DATABASE_PATH)
    if sys.argv[1:] == ["--check"]:
        print("Python и база SQLite готовы.")
        return
    if sys.argv[1:]:
        raise SystemExit("Использование: python storage/service.py [--check]")
    if os.environ.get("VPN_LOCAL_CONTROLLER") == "1":
        from app.vpn_reconcile import reconcile_all
        from app.wg_controller import LocalWireGuardController
        def reconcile_loop():
            controller = LocalWireGuardController()
            had_scan_error = False
            while True:
                try:
                    reconcile_all(controller, path=database.DATABASE_PATH)
                    if had_scan_error:
                        from contextlib import closing
                        with closing(vpn_devices._connect(database.DATABASE_PATH)) as db:
                            with db:
                                vpn_alerts.report(db, 0, 'scan', 'scan_error', int(time.time()))
                                vpn_alerts.resolve(db, 0, int(time.time()))
                        had_scan_error = False
                except Exception:
                    had_scan_error = True
                    print('VPN_RECONCILE_SCAN_ERROR', file=sys.stderr, flush=True)
                    try:
                        from contextlib import closing
                        with closing(vpn_devices._connect(database.DATABASE_PATH)) as db:
                            with db:
                                vpn_alerts.report(db, 0, 'scan', 'scan_error', int(time.time()))
                    except Exception:
                        pass
                threading.Event().wait(60)
        threading.Thread(target=reconcile_loop, daemon=True, name="vpn-reconcile").start()
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
