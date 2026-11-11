"""Small cross-domain helpers (Architecture Spec section 5: shared code
lives in core/; core depends on no app)."""
from __future__ import annotations

import re

from django.utils import timezone


def utcnow():
    """The one clock the backend trusts (ARCH-006)."""
    return timezone.now()


def normalize_phone(value: str) -> str:
    """Canonicalise an Iranian mobile number to the 09xxxxxxxxx form.

    Accepts 09..., +98..., 0098... and bare 98... inputs; strips spaces
    and separators. This is the single normalisation boundary used by the
    accounts app (task T-005) - never normalise phone numbers elsewhere.
    """
    digits = re.sub(r"[^\d+]", "", str(value))
    if digits.startswith("+98"):
        digits = "0" + digits[3:]
    elif digits.startswith("0098"):
        digits = "0" + digits[4:]
    elif digits.startswith("98") and len(digits) == 12:
        digits = "0" + digits[2:]
    return digits
