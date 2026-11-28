"""Reproduction and verification tests for T-046 m3 (atomic OTP rate-limit & verify attempts)."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from apps.accounts.services import get_redis_client, otp_redis_key, request_otp, verify_otp
from apps.accounts.sms import get_sms_sender, reset_fake_sms_sender
from core.exceptions import OtpExpiredError, OtpInvalidError, OtpRateLimitedError


@pytest.fixture(autouse=True)
def clean_otp_redis():
    sender = reset_fake_sms_sender()
    client = get_redis_client()
    for key in client.scan_iter("otp:*"):
        client.delete(key)
    yield sender
    sender.reset()
    for key in client.scan_iter("otp:*"):
        client.delete(key)


@pytest.mark.django_db(transaction=True)
def test_request_otp_concurrent_rate_limit_enforces_exact_cap():
    phone = "09120001111"
    workers = 10
    barrier = Barrier(workers)

    def _call(idx: int) -> str:
        barrier.wait(timeout=5)
        try:
            request_otp(phone, ip=f"10.1.0.{idx}")
            return "ok"
        except OtpRateLimitedError:
            return "rate_limited"

    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(_call, range(workers)))

    assert results.count("ok") == 3
    assert results.count("rate_limited") == 7


@pytest.mark.django_db(transaction=True)
def test_verify_otp_concurrent_attempts_burns_at_exact_5():
    phone = "09120002222"
    request_otp(phone, ip="10.2.0.1")
    real_code = get_sms_sender().last_code_for(phone)
    wrong_code = "00000" if real_code != "00000" else "99999"

    # First do 3 sequential wrong attempts so attempts=3
    for _ in range(3):
        with pytest.raises(OtpInvalidError):
            verify_otp(phone, wrong_code)

    # Now fire 5 concurrent wrong attempts; attempts 4 and 5 must burn the OTP,
    # and none of the concurrent calls may leave attempts < 5 or fail to burn.
    workers = 5
    barrier = Barrier(workers)

    def _verify(_idx: int) -> str:
        barrier.wait(timeout=5)
        try:
            verify_otp(phone, wrong_code)
            return "ok"
        except (OtpInvalidError, OtpExpiredError) as exc:
            return exc.error_code

    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(_verify, range(workers)))

    assert "ok" not in results
    # Key must be burned after reaching 5 attempts
    redis_client = get_redis_client()
    assert redis_client.get(otp_redis_key(phone)) is None
    # Exactly 2 of the 5 concurrent calls should see OTP_INVALID (4th and 5th);
    # the remaining 3 should see OTP_EXPIRED (key already burned).
    assert results.count("OTP_INVALID") == 2
    assert results.count("OTP_EXPIRED") == 3
