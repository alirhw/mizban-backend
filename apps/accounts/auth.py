"""Session authentication for Miz Ban API (Task T-007 / TD-006).

Replaces the temporary MinimalAuth development bridge. Every protected
endpoint authenticates exclusively via a real Django session cookie
established by a successful OTP verification.
"""
from __future__ import annotations

from typing import Any

from ninja.security import SessionAuth


class ActiveSessionAuth(SessionAuth):
    """Django session cookie authentication with CSRF enforcement (TD-006)."""

    def authenticate(self, request: Any, key: str | None) -> Any:
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated and getattr(user, "is_active", False):
            return user
        return None


auth = ActiveSessionAuth()
