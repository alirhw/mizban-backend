"""Celery tasks for booking lifecycle automation (FR-22 / Spec 009)."""
from __future__ import annotations

import logging

from celery import shared_task

from apps.bookings.services import complete_expired_bookings
from core.exceptions import DomainError, InvalidStatusTransitionError

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    name="bookings.complete_expired_bookings",
    max_retries=3,
    default_retry_delay=60,
)
def complete_expired_bookings_task(self) -> int:
    """Auto-complete elapsed CONFIRMED bookings with bounded retries on transient failures."""
    try:
        return complete_expired_bookings()
    except (InvalidStatusTransitionError, DomainError, ValueError, TypeError) as exc:
        logger.error(
            "Deterministic error in complete_expired_bookings_task: exc=%s",
            type(exc).__name__,
        )
        raise
    except Exception as exc:
        logger.error(
            "Transient error in complete_expired_bookings_task: exc=%s retry=%d/%d",
            type(exc).__name__,
            self.request.retries,
            self.max_retries,
        )
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc)
        raise
