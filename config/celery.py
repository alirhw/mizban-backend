"""Celery application for Miz Ban (broker: Redis, per TDR stack table).

Background work allowed by the Architecture Spec (section 20): panorama
image processing, SMS sending, periodic cleanup of expired booking locks.
"""
import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")

app = Celery("mizban")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
