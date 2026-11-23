"""Account services: OTP generation, rate limiting, and verification in Redis (Task T-006 / TD-006).

Invariants:
- 5-digit OTP codes generated via `secrets` (CSPRNG), never `random`.
- Only SHA-256 hash of the code is stored in Redis under `otp:{phone}` with 120s TTL.
- Rate limits: max 3 requests / 10 minutes per phone AND per IP (`OTP_RATE_LIMITED`, HTTP 429).
- Max 5 failed verify attempts per code; 5th failure burns (deletes) the code.
- Successful verify deletes the code immediately (single-use) and resolves the User
  without downgrading existing roles (VENUE_OWNER / ADMIN stay unchanged).
- Never log OTP codes or full phone numbers (AGENTS.md).
- Session cookie issuance is deferred to Task T-007.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import secrets
from typing import Any

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError
import redis as redis_lib

from apps.accounts.models import UserRole
from apps.accounts.sms import get_sms_sender
from core.exceptions import OtpExpiredError, OtpInvalidError, OtpRateLimitedError
from core.utils import normalize_phone

logger = logging.getLogger(__name__)

User = get_user_model()

OTP_LENGTH = 5
OTP_DEFAULT_TTL_SECONDS = 120
OTP_RATE_LIMIT_MAX_REQUESTS = 3
OTP_RATE_LIMIT_WINDOW_SECONDS = 600
OTP_MAX_ATTEMPTS = 5

_PHONE_PATTERN = re.compile(r"^09\d{9}$")
_DUMMY_SHA256_HEX = hashlib.sha256(b"00000").hexdigest()


def get_otp_ttl_seconds() -> float:
    """Return configured OTP TTL in seconds (default 120s per TD-006)."""
    return float(getattr(settings, "OTP_TTL_SECONDS", OTP_DEFAULT_TTL_SECONDS))


def get_redis_client() -> redis_lib.Redis:
    """Return a Redis client using the project's configured REDIS_URL."""
    return redis_lib.Redis.from_url(
        settings.REDIS_URL,
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=2,
    )


def validate_iranian_phone(phone: str) -> str:
    """Normalise via core.utils.normalize_phone and enforce 09xxxxxxxxx."""
    normalized = normalize_phone(phone)
    if not _PHONE_PATTERN.fullmatch(normalized):
        raise DjangoValidationError(
            {"phone": ["Enter a valid Iranian mobile number (e.g. 09123456789)."]}
        )
    return normalized


def otp_redis_key(normalized_phone: str) -> str:
    return f"otp:{normalized_phone}"


def otp_phone_rate_key(normalized_phone: str) -> str:
    return f"otp:rate:phone:{normalized_phone}"


def otp_ip_rate_key(ip: str) -> str:
    return f"otp:rate:ip:{ip}"


def _hash_otp_code(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def request_otp(phone: str, *, ip: str) -> int:
    """Generate a 5-digit OTP, store its SHA-256 hash in Redis, and send via SMS adapter.

    Enforces max 3 requests per 10 minutes per phone and per IP.
    Replaces any previous active OTP for the phone immediately.
    """
    normalized_phone = validate_iranian_phone(phone)
    client_ip = (ip or "unknown").strip() or "unknown"

    client = get_redis_client()
    phone_rate_key = otp_phone_rate_key(normalized_phone)
    ip_rate_key = otp_ip_rate_key(client_ip)

    phone_count = int(client.get(phone_rate_key) or 0)
    ip_count = int(client.get(ip_rate_key) or 0)
    if phone_count >= OTP_RATE_LIMIT_MAX_REQUESTS or ip_count >= OTP_RATE_LIMIT_MAX_REQUESTS:
        logger.warning("OTP request rate limit exceeded.")
        raise OtpRateLimitedError()

    pipe = client.pipeline()
    pipe.incr(phone_rate_key)
    pipe.expire(phone_rate_key, OTP_RATE_LIMIT_WINDOW_SECONDS, nx=True)
    pipe.incr(ip_rate_key)
    pipe.expire(ip_rate_key, OTP_RATE_LIMIT_WINDOW_SECONDS, nx=True)
    pipe.execute()

    code = f"{secrets.randbelow(10**OTP_LENGTH):0{OTP_LENGTH}d}"
    ttl_seconds = get_otp_ttl_seconds()
    ttl_ms = max(1, int(ttl_seconds * 1000))

    payload = json.dumps({"code_hash": _hash_otp_code(code), "attempts": 0})
    client.set(otp_redis_key(normalized_phone), payload, px=ttl_ms)

    get_sms_sender().send_otp(normalized_phone, code)
    logger.info("OTP request processed via SMS adapter.")
    return int(ttl_seconds) if ttl_seconds >= 1 else 1


def verify_otp(phone: str, code: str) -> Any:
    """Verify a 5-digit OTP in constant time and resolve (get_or_create) the User.

    - Missing/expired OTP -> OtpExpiredError (400 OTP_EXPIRED).
    - Wrong code -> increments attempts (burns on 5th failure) -> OtpInvalidError (400 OTP_INVALID).
    - Success -> deletes OTP immediately (single-use) and returns User (role preserved if existing).
    """
    normalized_phone = validate_iranian_phone(phone)
    candidate_hash = _hash_otp_code(str(code).strip())

    client = get_redis_client()
    key = otp_redis_key(normalized_phone)
    raw = client.get(key)

    if raw is None:
        # Constant-time dummy comparison so missing/expired path does not shortcut timing
        hmac.compare_digest(candidate_hash, _DUMMY_SHA256_HEX)
        raise OtpExpiredError()

    record = json.loads(raw)
    expected_hash = record["code_hash"]
    attempts = int(record.get("attempts", 0))

    if not hmac.compare_digest(candidate_hash, expected_hash):
        attempts += 1
        if attempts >= OTP_MAX_ATTEMPTS:
            client.delete(key)
            logger.warning("OTP verification burned after maximum failed attempts.")
        else:
            record["attempts"] = attempts
            client.set(key, json.dumps(record), keepttl=True)
            logger.info("OTP verification failed attempt recorded.")
        raise OtpInvalidError()

    # Single-use: delete the record immediately on success
    client.delete(key)

    user = User.objects.filter(phone=normalized_phone).first()
    if user is None:
        try:
            user = User.objects.create_user(phone=normalized_phone, role=UserRole.CUSTOMER)
        except IntegrityError:
            user = User.objects.get(phone=normalized_phone)

    logger.info("OTP verification succeeded.")
    return user
