"""Minimal authenticated identity bridge for Miz Ban (Task T-009).

Architecture note: Full session/access layer and OTP login (Task T-007)
are deferred. This module provides the minimal authenticated-identity
bridge required by T-009 to identify callers (owner, admin, customer)
and attach them to request.auth.

SECURITY GUARD (Task T-009 Gate Requirement):
TODO(T-007): Replace this temporary identity bridge with production-grade
signed session tokens, Redis session store, and OTP authentication.
The 'X-User-Phone' header and 'Bearer <phone>' lookup paths are strictly
restricted to development environments (settings.DEBUG=True) and must be
completely rejected in all non-debug settings modules.
"""
from __future__ import annotations

from typing import Any

from django.conf import settings
from django.contrib.auth import get_user_model
from ninja.security import HttpBearer

from core.utils import normalize_phone

User = get_user_model()


class MinimalAuth(HttpBearer):
    """Authentication bridge for Django Ninja.

    Supports:
    1. Active Django session (request.user.is_authenticated) - used by session/browser and test force_login.
    2. Bearer token matching a canonical phone number (e.g. 'Bearer 09123456789') [DEBUG ONLY].
    3. Custom 'X-User-Phone' header fallback for API clients and test runners [DEBUG ONLY].

    Returns the User model instance, or None if unauthenticated.
    """

    def __call__(self, request: Any) -> Any:
        # 1. Check existing authenticated session on request (safe in all environments)
        user = getattr(request, "user", None)
        if user and user.is_authenticated and user.is_active:
            return user

        # 2. Check X-User-Phone header (DEBUG=True only)
        # TODO(T-007): Remove header impersonation fallback once full session auth is built
        if getattr(settings, "DEBUG", False):
            phone_header = request.headers.get("X-User-Phone")
            if phone_header:
                cleaned = normalize_phone(phone_header)
                user = User.objects.filter(phone=cleaned, is_active=True).first()
                if user:
                    return user

        # 3. Fallback to HttpBearer (Authorization: Bearer <token>)
        return super().__call__(request)

    def authenticate(self, request: Any, token: str) -> Any:
        # TODO(T-007): Replace phone-as-bearer token lookup with verified JWT or signed session token
        # SECURITY GUARD: Disallow phone-based bearer token when DEBUG=False
        if not getattr(settings, "DEBUG", False):
            return None

        if not token:
            return None
        cleaned = normalize_phone(token)
        return User.objects.filter(phone=cleaned, is_active=True).first()


auth = MinimalAuth()
