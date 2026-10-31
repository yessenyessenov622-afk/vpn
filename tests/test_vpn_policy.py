import tempfile
import unittest
from pathlib import Path

from app import database
from app.vpn_policy import Action, Device, ResultStatus, Subscription, apply_decision, decide


class FakeVPN:
    """Имитация существует только в тестах; сетевых подключений нет."""
    def __init__(self):
        self.states = {}
        self.calls = []
        self.fail = False
        self.fail_after_apply = False
        self.acknowledgment = True

    def set_access(self, device, enabled):
        self.calls.append((device.user_id, device.device_id, enabled))
        if self.fail:
            raise OSError("simulated failure")
        if self.acknowledgment is True:
            self.states[(device.user_id, device.device_id)] = enabled
        if self.fail_after_apply:
            raise OSError("simulated lost confirmation")
        return self.acknowledgment


class VPNPolicyTests(unittest.TestCase):
    def setUp(self):
        self.vpn = FakeVPN()
        self.disabled = Device(user_id=1, device_id="phone", prepared=True, access_enabled=False)
        self.enabled = Device(user_id=1, device_id="phone", prepared=True, access_enabled=True)
        self.active = Subscription(user_id=1, expires_at=2000)

    def test_active_subscription_requires_enable_and_confirmation(self):
        decision = decide(self.disabled, self.active, now=1000)
        self.assertEqual(decision.action, Action.ENABLE)
        self.assertFalse(decision.device.access_enabled)
        self.assertEqual(self.vpn.calls, [])
        result = apply_decision(decision, self.vpn)
        self.assertEqual(result.status, ResultStatus.CONFIRMED)
        self.assertTrue(result.device.access_enabled)
        self.assertFalse(self.disabled.access_enabled)

    def test_expired_and_missing_subscriptions_require_disable(self):
        for subscription, now in ((self.active, 2001), (None, 1000)):
            decision = decide(self.enabled, subscription, now=now)
            self.assertEqual(decision.action, Action.DISABLE)
            result = apply_decision(decision, self.vpn)
            self.assertEqual(result.status, ResultStatus.CONFIRMED)
            self.assertFalse(result.device.access_enabled)

    def test_exact_expiration_in_utc_seconds(self):
        self.assertEqual(decide(self.enabled, self.active, now=1999).action, Action.NONE)
        self.assertEqual(decide(self.enabled, self.active, now=2000).action, Action.DISABLE)
        self.assertEqual(decide(self.disabled, self.active, now=2000).action, Action.NONE)

    def test_renewal_after_expiration_and_repeat_check(self):
        first = apply_decision(decide(self.enabled, self.active, now=2000), self.vpn)
        self.assertFalse(first.device.access_enabled)
        renewed = Subscription(user_id=1, expires_at=3000)
        decision = decide(first.device, renewed, now=2100)
        self.assertEqual(decision.action, Action.ENABLE)
        result = apply_decision(decision, self.vpn)
        self.assertTrue(result.device.access_enabled)
        no_change = apply_decision(decide(result.device, renewed, now=2100), self.vpn)
        self.assertEqual(no_change.status, ResultStatus.NO_CHANGE)
        self.assertEqual(len(self.vpn.calls), 2)

    def test_no_grant_for_unprepared_device(self):
        unprepared = Device(user_id=1, device_id="new", prepared=False, access_enabled=False)
        self.assertEqual(decide(unprepared, self.active, now=1000).action, Action.NONE)
        self.assertEqual(apply_decision(decide(self.disabled, None, now=1000), self.vpn).status, ResultStatus.NO_CHANGE)
        self.assertEqual(self.vpn.calls, [])

    def test_multiple_users_are_independent(self):
        other = Device(user_id=2, device_id="phone", prepared=True, access_enabled=True)
        one = apply_decision(decide(self.disabled, self.active, now=1000), self.vpn)
        two = apply_decision(decide(other, Subscription(user_id=2, expires_at=900), now=1000), self.vpn)
        self.assertTrue(one.device.access_enabled)
        self.assertFalse(two.device.access_enabled)
        self.assertTrue(self.vpn.states[(1, "phone")])
        self.assertFalse(self.vpn.states[(2, "phone")])
        with self.assertRaises(ValueError):
            decide(other, self.active, now=1000)

    def test_error_keeps_last_confirmed_state_and_allows_retry(self):
        self.vpn.fail = True
        decision = decide(self.enabled, self.active, now=2000)
        failed = apply_decision(decision, self.vpn)
        self.assertEqual(failed.status, ResultStatus.FAILED)
        self.assertTrue(failed.device.access_enabled)
        self.vpn.fail = False
        retry = decide(failed.device, self.active, now=2000)
        self.assertEqual(retry.action, Action.DISABLE)
        confirmed = apply_decision(retry, self.vpn)
        self.assertEqual(confirmed.status, ResultStatus.CONFIRMED)
        self.assertFalse(confirmed.device.access_enabled)

    def test_unconfirmed_response_is_not_success(self):
        for value in (False, None, 1):
            self.vpn.acknowledgment = value
            result = apply_decision(decide(self.disabled, self.active, now=1000), self.vpn)
            self.assertEqual(result.status, ResultStatus.FAILED)
            self.assertFalse(result.device.access_enabled)

    def test_lost_confirmation_is_not_reported_as_success(self):
        self.vpn.fail_after_apply = True
        first = apply_decision(decide(self.disabled, self.active, now=1000), self.vpn)
        self.assertEqual(first.status, ResultStatus.FAILED)
        self.assertFalse(first.device.access_enabled)
        self.assertTrue(self.vpn.states[(1, "phone")])  # Сервер мог выполнить запрос до ошибки.
        self.vpn.fail_after_apply = False
        retry = apply_decision(decide(first.device, self.active, now=1000), self.vpn)
        self.assertEqual(retry.status, ResultStatus.CONFIRMED)
        self.assertTrue(retry.device.access_enabled)

    def test_existing_subscription_data_in_temporary_database(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.sqlite3"
            database.initialize(path)
            database.register_user(1, path)
            row = database.grant_subscription(1, 1, path, now=1000)
            subscription = Subscription(user_id=1, expires_at=row["expires_at"])
            self.assertEqual(decide(self.disabled, subscription, now=1000).action, Action.ENABLE)
            self.assertEqual(decide(self.enabled, subscription, now=row["expires_at"]).action, Action.DISABLE)
            self.assertEqual(database.get_subscription(1, path), row)


if __name__ == "__main__":
    unittest.main()
