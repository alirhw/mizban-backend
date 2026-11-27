"""SMS sender interface, dev/test adapters, and factory (Task T-006 / TD-006).

Provider decision (2026-11-20, Decision 4): SMS.ir is the chosen OTP SMS
provider, to be plugged in post-MVP once the domain exists. No real provider
SDK, endpoint, or credentials exist here; OTP logic talks strictly to the
SmsSender protocol resolved via get_sms_sender().
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from django.conf import settings


@dataclass(frozen=True)
class SentOtpMessage:
    """In-memory record of an OTP message dispatched through FakeSmsSender."""

    phone: str
    code: str


@runtime_checkable
class SmsSender(Protocol):
    """Narrow SMS sender contract isolating OTP delivery from domain services."""

    def send_otp(self, phone: str, code: str) -> None:
        """Deliver an OTP code to a canonical Iranian mobile number."""
        ...


class ConsoleSmsSender:
    """Local development SMS sender.

    Writes the OTP code to stdout ONLY when settings.DEBUG is True.
    Never prints or logs anything when DEBUG is False, and never writes
    to Python's logging module.
    """

    def send_otp(self, phone: str, code: str) -> None:
        if not getattr(settings, "DEBUG", False):
            return
        masked = f"***{phone[-4:]}" if len(phone) >= 4 else "****"
        sys.stdout.write(f"[DEV SMS] OTP for {masked}: {code}\n")
        sys.stdout.flush()


class FakeSmsSender:
    """In-memory SMS sender for automated tests (zero network, zero logs)."""

    def __init__(self) -> None:
        self.sent_messages: list[SentOtpMessage] = []

    def send_otp(self, phone: str, code: str) -> None:
        self.sent_messages.append(SentOtpMessage(phone=phone, code=code))

    def reset(self) -> None:
        self.sent_messages.clear()

    def last_code_for(self, phone: str) -> str | None:
        for msg in reversed(self.sent_messages):
            if msg.phone == phone:
                return msg.code
        return None


_SMS_SENDERS: dict[str, type[SmsSender]] = {
    "console": ConsoleSmsSender,
    "fake": FakeSmsSender,
}

_SMS_INSTANCES: dict[str, SmsSender] = {}


def register_sms_sender(name: str, sender_cls: type[SmsSender]) -> None:
    """Register an SMS sender adapter class by name."""
    key = name.lower()
    _SMS_SENDERS[key] = sender_cls
    _SMS_INSTANCES.pop(key, None)


def get_sms_sender(sender_name: str | None = None) -> SmsSender:
    """Factory returning the singleton SMS sender configured via settings.SMS_SENDER."""
    name = (sender_name or str(getattr(settings, "SMS_SENDER", "console") or "console")).lower()
    if name not in _SMS_INSTANCES:
        sender_cls = _SMS_SENDERS.get(name)
        if not sender_cls:
            raise ValueError(
                f"Unknown SMS sender '{name}'. Registered senders: {list(_SMS_SENDERS.keys())}"
            )
        _SMS_INSTANCES[name] = sender_cls()
    return _SMS_INSTANCES[name]


def reset_fake_sms_sender() -> FakeSmsSender:
    """Reset the fake SMS sender singleton and clear recorded messages."""
    sender = get_sms_sender("fake")
    if not isinstance(sender, FakeSmsSender):
        raise TypeError(f"Expected FakeSmsSender for 'fake', got {type(sender).__name__}")
    sender.reset()
    return sender
