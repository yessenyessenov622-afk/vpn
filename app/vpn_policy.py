"""Локальные правила будущего VPN. Подключения к серверу здесь нет.

Время — Unix-секунды UTC, как в таблице test_subscriptions. Состояние
устройства — последнее подтверждённое состояние, а не гарантия текущего
состояния сервера после ошибки или потери связи.
"""
from dataclasses import dataclass, replace
from enum import Enum
from time import time
from typing import Protocol


class Action(Enum):
    NONE = "none"
    ENABLE = "enable"
    DISABLE = "disable"
    VERIFY = "verify"


class ResultStatus(Enum):
    NO_CHANGE = "no_change"
    CONFIRMED = "confirmed"
    FAILED = "failed"
    NEEDS_CHECK = "needs_check"


@dataclass(frozen=True)
class Device:
    user_id: int
    device_id: str
    prepared: bool
    access_enabled: bool | None  # None: требуется проверка на сервере.

    def __post_init__(self):
        if type(self.user_id) is not int or self.user_id <= 0:
            raise ValueError("Invalid user ID")
        if not isinstance(self.device_id, str) or not self.device_id.strip():
            raise ValueError("Invalid device ID")
        if type(self.prepared) is not bool or (self.access_enabled is not None and type(self.access_enabled) is not bool):
            raise ValueError("Device state must be a boolean or unknown")


@dataclass(frozen=True)
class Subscription:
    user_id: int
    expires_at: int

    def __post_init__(self):
        if type(self.user_id) is not int or self.user_id <= 0:
            raise ValueError("Invalid user ID")
        if type(self.expires_at) is not int or self.expires_at < 0:
            raise ValueError("Expiration must be UTC Unix seconds")


@dataclass(frozen=True)
class Decision:
    action: Action
    device: Device


@dataclass(frozen=True)
class Result:
    action: Action
    status: ResultStatus
    device: Device


class VPNController(Protocol):
    def set_access(self, device: Device, enabled: bool) -> bool:
        """Вернуть True только после подтверждения действия сервером."""


def decide(device: Device, subscription: Subscription | None, *, now: int | None = None) -> Decision:
    """Определить требуемое действие; сервер и состояние устройства не меняются."""
    current = int(time()) if now is None else now
    if type(current) is not int or current < 0:
        raise ValueError("Current time must be UTC Unix seconds")
    if subscription is not None and subscription.user_id != device.user_id:
        raise ValueError("Subscription belongs to a different user")

    if device.access_enabled is None:
        return Decision(Action.VERIFY, device)

    active = subscription is not None and subscription.expires_at > current
    if active and device.prepared and not device.access_enabled:
        return Decision(Action.ENABLE, device)
    if not active and device.access_enabled:
        return Decision(Action.DISABLE, device)
    return Decision(Action.NONE, device)


def apply_decision(decision: Decision, controller: VPNController) -> Result:
    """Применить решение через явно переданный контроллер.

    При отказе или ошибке возвращается последнее подтверждённое состояние;
    фактическое состояние сервера может быть неизвестно. Реальный контроллер
    должен поддерживать безопасное повторение операции и сверку состояния.
    """
    if decision.action is Action.NONE:
        return Result(Action.NONE, ResultStatus.NO_CHANGE, decision.device)
    if decision.action is Action.VERIFY:
        return Result(Action.VERIFY, ResultStatus.NEEDS_CHECK, decision.device)
    if decision.action not in (Action.ENABLE, Action.DISABLE):
        raise ValueError("Invalid action")
    enabled = decision.action is Action.ENABLE
    try:
        confirmed = controller.set_access(decision.device, enabled) is True
    except Exception:
        confirmed = False
    if not confirmed:
        return Result(decision.action, ResultStatus.FAILED, decision.device)
    return Result(decision.action, ResultStatus.CONFIRMED, replace(decision.device, access_enabled=enabled))
