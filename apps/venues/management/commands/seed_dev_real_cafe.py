"""DEV-ONLY management command to seed 'real-cafe-dev' using the normal panorama upload & processing pipeline.

Refuses to run when DEBUG=False. Never included in migrations or production fixtures.
Leaves 'sample-cafe-dev' completely untouched. Supports --clear to remove 'real-cafe-dev'.
"""
from __future__ import annotations

from datetime import time
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts.models import UserRole
from apps.panoramas.models import PanoramaStatus, Space, TablePin
from apps.panoramas.schemas import TablePinCreateIn
from apps.panoramas.services import create_table_pin_for_space, upload_panorama_for_space
from apps.panoramas.tasks import process_panorama_image
from apps.venues.models import DesignAddon, OperatingHours, SubscriptionPlan, Venue, VenueType
from apps.venues.services import activate_subscription

REAL_VENUE_SLUG = "real-cafe-dev"
REAL_VENUE_NAME = "کافه واقعی — توسعه"
SAMPLE_OWNER_PHONE = "09120009999"
SAMPLE_ADMIN_PHONE = "09120009998"
SAMPLE_PLAN_NAME = "طرح نمونه توسعه"
IMAGE_REL_PATH = Path("dev_assets") / "cafe-panorama-360-real.jpg"


class Command(BaseCommand):
    help = "Seed (or --clear) DEV-ONLY 'real-cafe-dev' via the normal panorama upload/processing pipeline."

    def add_arguments(self, parser):
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Remove the DEV-ONLY 'real-cafe-dev' venue and its panorama/pins.",
        )

    def handle(self, *args, **options):
        if not getattr(settings, "DEBUG", False):
            raise CommandError("seed_dev_real_cafe is strictly for local development (DEBUG=True).")

        if options["clear"]:
            deleted, _ = Venue.objects.filter(slug=REAL_VENUE_SLUG).delete()
            self.stdout.write(self.style.SUCCESS(f"Cleared '{REAL_VENUE_SLUG}' (rows removed: {deleted})."))
            return

        image_path = Path(settings.BASE_DIR) / IMAGE_REL_PATH
        if not image_path.is_file():
            raise CommandError(f"Missing panorama source image at {image_path}")

        User = get_user_model()
        with transaction.atomic():
            owner, _ = User.objects.get_or_create(
                phone=SAMPLE_OWNER_PHONE,
                defaults={"role": UserRole.VENUE_OWNER},
            )
            admin, _ = User.objects.get_or_create(
                phone=SAMPLE_ADMIN_PHONE,
                defaults={"role": UserRole.ADMIN, "is_staff": True},
            )

            venue, _ = Venue.objects.get_or_create(
                slug=REAL_VENUE_SLUG,
                defaults={
                    "owner": owner,
                    "name": REAL_VENUE_NAME,
                    "city": "تهران",
                    "venue_type": VenueType.CAFE,
                    "address": "خیابان کریم‌خان — نمونه توسعه با تصویر ۳۶۰ واقعی",
                    "description": "داده نمونه توسعه با تصویر پانورامای ۳۶۰ درجه واقعی‌نما (تولید هوش مصنوعی، غیرعکاسی).",
                    "is_approved": True,
                },
            )
            if not venue.is_approved:
                venue.is_approved = True
                venue.save(update_fields=["is_approved", "updated_at"])

            plan, _ = SubscriptionPlan.objects.get_or_create(
                name=SAMPLE_PLAN_NAME,
                defaults={"duration_days": 365, "price_toman": 0, "is_active": True},
            )
            if not venue.has_active_subscription():
                activate_subscription(venue, plan=plan, activated_by=admin, note="DEV-ONLY real-cafe-dev seed")

            space, _ = Space.objects.get_or_create(
                venue=venue,
                name="سالن اصلی — کاشی فیروزه‌ای",
                defaults={"display_order": 1, "is_active": True},
            )

        # Normal product upload + processing pipeline (outside transaction so on_commit / DB reads see UPLOADED)
        if not space.active_panorama or space.active_panorama.status != PanoramaStatus.READY:
            image_bytes = image_path.read_bytes()
            uploaded = SimpleUploadedFile(
                name="cafe-panorama-360-real.jpg",
                content=image_bytes,
                content_type="image/jpeg",
            )
            pano = upload_panorama_for_space(owner, space.id, uploaded)
            process_panorama_image(str(pano.id))
            pano.refresh_from_db()
            space.refresh_from_db()
        else:
            pano = space.active_panorama

        # 4 visible table pins spread across the room in cafe-panorama-360-real.jpg
        pin_specs = [
            ("میز ۱ (پنجره چپ)", 3, -27.0, -148.0, 65_000, False, "میز چوبی سه‌نفره کنار پنجره و فرش ایرانی"),
            ("میز ۲ (پنجره وسط)", 3, -16.0, -97.0, 75_000, False, "میز کنار پنجره میانی با نور طبیعی"),
            ("میز ۳ (کتابخانه)", 2, -13.0, -40.0, 90_000, False, "میز دنج دونفره کنار قفسه کتاب و گلدان‌ها"),
            ("میز ۴ (پنجره راست)", 2, -20.0, 165.0, 110_000, True, "میز دونفره سمت راست کنار پنجره"),
        ]
        for table_number, capacity, pitch, yaw, fee, is_smoking, desc in pin_specs:
            if not TablePin.objects.filter(venue=venue, table_number=table_number).exists():
                create_table_pin_for_space(
                    owner,
                    space.id,
                    TablePinCreateIn(
                        table_number=table_number,
                        capacity=capacity,
                        pitch=pitch,
                        yaw=yaw,
                        panorama_image_id=pano.id,
                        description=desc,
                        reservation_fee_toman=fee,
                        is_smoking=is_smoking,
                        is_active=True,
                    ),
                )

        with transaction.atomic():
            for weekday in OperatingHours.Weekday.values:
                OperatingHours.objects.update_or_create(
                    venue=venue,
                    weekday=weekday,
                    defaults={
                        "open_time": time(9, 0),
                        "close_time": time(23, 0),
                    },
                )

            sample_addons = [
                ("گل‌آرایی میز", 120_000),
                ("شمع و دیزاین رمانتیک", 80_000),
                ("کیک کوچک تولد", 250_000),
            ]
            for title, fee in sample_addons:
                DesignAddon.objects.update_or_create(
                    venue=venue,
                    title=title,
                    defaults={
                        "fee": fee,
                        "is_active": True,
                    },
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded DEV-ONLY venue '{venue.name}' (id={venue.id}, slug={venue.slug}), "
                f"space_id={space.id}, pano_id={pano.id}, status={pano.status}, "
                f"processed={pano.width}x{pano.height} ({pano.file_size_bytes} bytes, "
                f"webp={pano.webp_file.name}), pins={space.table_pins.count()}, "
                f"hours={venue.operating_hours.count()}, "
                f"addons={venue.design_addons.filter(is_active=True).count()}"
            )
        )
