"""Base settings for Miz Ban - shared by every environment.

Architecture Spec section 24: shared configuration lives here; overrides
live in development.py / production.py. All secrets come from the
environment via django-environ; nothing secret is hard-coded.
Business timestamps are stored in UTC (USE_TZ=True); Jalali conversion
happens only at presentation time, in core.jalali.
"""
from pathlib import Path
from typing import Any

import environ

from core.observability import init_sentry

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, []),
)
_env_file = BASE_DIR / ".env"
if _env_file.exists():
    environ.Env.read_env(_env_file)

SECRET_KEY = env("SECRET_KEY", default="")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env("ALLOWED_HOSTS")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Domain apps (Architecture Spec section 4), ordered by the dependency
    # graph in section 5: foundations first.
    "apps.accounts",
    "apps.venues",
    "apps.panoramas",
    "apps.scheduling",
    "apps.bookings",
    "apps.billing",
    "apps.wallets",
    "apps.reviews",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "core.observability.RequestIdMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# Custom user model (phone-number identity, TD-006). This must exist before
# the first migration of any dependent app - see task T-005.
AUTH_USER_MODEL = "accounts.User"

DATABASES = {
    "default": env.db(
        "DATABASE_URL",
        default="postgres://mizban:mizban@localhost:5432/mizban",
    )
}

# PostgreSQL connection-level bounded wait options (Task T-014 / Spike 02):
# lock_timeout = 5000ms (5s) prevents unbounded waits on row / table locks.
# statement_timeout = 10000ms (10s) acts as a safety ceiling for query execution.
if DATABASES["default"].get("ENGINE") == "django.db.backends.postgresql":
    DATABASES["default"].setdefault("OPTIONS", {})
    _existing_options = DATABASES["default"]["OPTIONS"].get("options", "")
    _timeout_flags = "-c lock_timeout=5000 -c statement_timeout=10000"
    DATABASES["default"]["OPTIONS"]["options"] = (
        f"{_existing_options} {_timeout_flags}".strip()
    )

REDIS_URL = env("REDIS_URL", default="redis://localhost:6379/0")
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": env("CACHE_URL", default="redis://localhost:6379/1"),
    }
}

# NOTE (ARCH-004): the cache is for venue metadata and OTP codes ONLY.
# Slot availability and booking-lock state are never cached; PostgreSQL is
# the single authority for what is free or occupied.
CELERY_BROKER_URL = env("CELERY_BROKER_URL", default=REDIS_URL)
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", default=REDIS_URL)
CELERY_TIMEZONE = "UTC"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 300

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "fa-ir"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Miz Ban business constants (Product Definition section 6) ---
SLOT_DURATION_MINUTES = 90  # BR-001: each reservation slot is 90 minutes
SLOT_BUFFER_MINUTES = 30  # BR-001: plus a 30-minute cleaning buffer
BOOKING_MIN_LEAD_HOURS = 24  # BR-002: book at least 24h ahead
CANCELLATION_MIN_LEAD_HOURS = 36  # BR-004: cancel at least 36h ahead
BOOKING_LOCK_MINUTES = 10  # TD-004: temporary DB lock while paying

# --- Payment Gateway Configuration (Task T-020 / ARCH-005) ---
PAYMENT_GATEWAY_PROVIDER = env("PAYMENT_GATEWAY_PROVIDER", default="sandbox")
PAYMENT_GATEWAY_TIMEOUT_SECONDS = env.float("PAYMENT_GATEWAY_TIMEOUT_SECONDS", default=8.0)
PAYMENT_GATEWAY_CALLBACK_BASE_URL = env("PAYMENT_GATEWAY_CALLBACK_BASE_URL", default="http://127.0.0.1:8000")
SANDBOX_BASE_URL = env("SANDBOX_BASE_URL", default="https://sandbox.mizban.local")

# --- OTP & SMS Adapter Configuration (Task T-006 / TD-006) ---
SMS_SENDER = env("SMS_SENDER", default="console")
OTP_TTL_SECONDS = env.int("OTP_TTL_SECONDS", default=120)

# --- Session Cookie Configuration (Task T-007 / TD-006) ---
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = True

# --- Observability (Architecture Spec section 25 / Task T-031) ---
ENVIRONMENT = env("ENVIRONMENT", default=env("DJANGO_ENV", default="development"))
APP_RELEASE = env("APP_RELEASE", default="mizban-backend@0.1.0")
SENTRY_DSN = env("SENTRY_DSN", default="")
SENTRY_TRACES_SAMPLE_RATE = env.float("SENTRY_TRACES_SAMPLE_RATE", default=0.1)

init_sentry(
    dsn=SENTRY_DSN,
    environment=ENVIRONMENT,
    release=APP_RELEASE,
    traces_sample_rate=SENTRY_TRACES_SAMPLE_RATE,
)

LOGGING: dict[str, Any] = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "pii_request_id": {"()": "core.observability.PiiScrubbingFilter"},
    },
    "formatters": {
        "simple": {"format": "%(asctime)s %(levelname)s [%(request_id)s] %(name)s %(message)s"},
        "json": {"()": "core.observability.JsonLogFormatter"},
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "simple",
            "filters": ["pii_request_id"],
        },
    },
    "root": {"handlers": ["console"], "level": "INFO"},
}
