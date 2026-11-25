"""Development settings: debug on, local conveniences, fail-soft secrets.

Dev convenience (documented): when DATABASE_URL is not set in the
environment, fall back to a local SQLite file so `manage.py check` and the
test suite run with no services up. SQLite is NEVER proof of booking
concurrency behaviour - the race tests require PostgreSQL (TD-004).
"""
import os
import sys

from .base import *  # noqa: F401,F403
from .base import BASE_DIR

DEBUG = True
SECRET_KEY = SECRET_KEY or "dev-only-insecure-key-do-not-use-in-production"  # noqa: F405
ALLOWED_HOSTS = ["*"]
SESSION_COOKIE_SECURE = False
SANDBOX_BASE_URL = os.environ.get("SANDBOX_BASE_URL", "http://127.0.0.1:8001")

if not os.environ.get("SMS_SENDER") and "pytest" in sys.modules:
    SMS_SENDER = "fake"

if not os.environ.get("DATABASE_URL"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
