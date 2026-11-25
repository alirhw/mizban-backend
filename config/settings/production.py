"""Production settings: fail fast on missing mandatory configuration.

Secrets arrive only from the environment / secret store. If a required
value is absent, startup refuses to run (fail closed) - the error names
the variable but never prints a secret value.
"""
from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F401,F403

DEBUG = False

if not SECRET_KEY:  # noqa: F405
    raise ImproperlyConfigured("SECRET_KEY environment variable is required in production.")
if not ALLOWED_HOSTS:  # noqa: F405
    raise ImproperlyConfigured("ALLOWED_HOSTS environment variable is required in production.")

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SECURE_HSTS_SECONDS = 31_536_000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

# Structured JSON logging in production (Task T-031)
ENVIRONMENT = env("ENVIRONMENT", default=env("DJANGO_ENV", default="production"))  # noqa: F405
LOGGING["handlers"]["console"]["formatter"] = "json"  # noqa: F405
