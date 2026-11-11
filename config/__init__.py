# Importing the Celery app here registers it as soon as Django starts,
# so @shared_task decorators bind to this app (standard Celery/Django wiring).
from .celery import app as celery_app

__all__ = ("celery_app",)
