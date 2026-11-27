"""Management command to transition elapsed CONFIRMED bookings to COMPLETED (FR-22 / Spec 009)."""
from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.bookings.services import complete_expired_bookings, list_completable_booking_ids


class Command(BaseCommand):
    help = "Transition elapsed CONFIRMED bookings (end_at <= now) to COMPLETED."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="List eligible booking_ids without mutating database state.",
        )

    def handle(self, *args, **options) -> None:
        if options["dry_run"]:
            booking_ids = list_completable_booking_ids()
            ids_display = ", ".join(str(booking_id) for booking_id in booking_ids) if booking_ids else "none"
            self.stdout.write(f"[dry-run] Eligible bookings ({len(booking_ids)}): {ids_display}")
            return

        completed_count = complete_expired_bookings()
        self.stdout.write(self.style.SUCCESS(f"Completed {completed_count} expired booking(s)."))
