"""DEV-ONLY management command to seed a sample venue with a 4096x2048 WebP 360 panorama and table pins.

Refuses to run when DEBUG=False. Never included in migrations or production fixtures.
Supports --clear to remove the sample data cleanly.
"""
from __future__ import annotations

import io
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from PIL import Image, ImageDraw

from apps.accounts.models import UserRole
from apps.panoramas.models import PanoramaImage, PanoramaStatus, Space, TablePin
from apps.venues.models import SubscriptionPlan, Venue, VenueType
from apps.venues.services import activate_subscription

SAMPLE_VENUE_SLUG = "sample-cafe-dev"
SAMPLE_VENUE_NAME = "کافه نمونه — توسعه"
SAMPLE_OWNER_PHONE = "09120009999"
SAMPLE_ADMIN_PHONE = "09120009998"
SAMPLE_PLAN_NAME = "طرح نمونه توسعه"


def _build_synthetic_equirectangular_webp() -> tuple[bytes, bytes, int]:
    """Generate a clearly synthetic 4096x2048 equirectangular grid panorama + 512x256 thumb."""
    width, height = 4096, 2048
    img = Image.new("RGB", (width, height), color=(28, 36, 48))
    draw = ImageDraw.Draw(img)

    # Upper hemisphere (ceiling/sky) & lower hemisphere (floor)
    draw.rectangle([(0, 0), (width, height // 2)], fill=(45, 72, 108))
    draw.rectangle([(0, height // 2), (width, height)], fill=(78, 62, 50))

    # Horizon line (pitch = 0)
    draw.line([(0, height // 2), (width, height // 2)], fill=(240, 200, 90), width=6)

    # Vertical yaw grid lines every 45 degrees (512px intervals)
    for step in range(0, width, 512):
        draw.line([(step, 0), (step, height)], fill=(110, 145, 180), width=3)

    # Horizontal pitch lines
    for y in (512, 1536):
        draw.line([(0, y), (width, y)], fill=(120, 130, 145), width=2)

    # Clear synthetic label at center (yaw=0)
    draw.rectangle([(1650, 880), (2450, 1000)], fill=(20, 25, 34), outline=(240, 200, 90), width=4)
    draw.text((1730, 925), "DEV TEST PANORAMA 4096x2048 (SYNTHETIC)", fill=(255, 255, 255))

    webp_buf = io.BytesIO()
    img.save(webp_buf, format="WEBP", quality=82)
    webp_bytes = webp_buf.getvalue()

    thumb = img.resize((512, 256), Image.Resampling.LANCZOS)
    thumb_buf = io.BytesIO()
    thumb.save(thumb_buf, format="WEBP", quality=75)
    thumb_bytes = thumb_buf.getvalue()

    return webp_bytes, thumb_bytes, len(webp_bytes)


class Command(BaseCommand):
    help = "Seed (or --clear) DEV-ONLY sample venue, space, 4096x2048 WebP panorama, and table pins."

    def add_arguments(self, parser):
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Remove the DEV-ONLY sample venue and related panorama/pins.",
        )

    def handle(self, *args, **options):
        if not getattr(settings, "DEBUG", False):
            raise CommandError("seed_dev_panorama is strictly for local development (DEBUG=True).")

        if options["clear"]:
            deleted, _ = Venue.objects.filter(slug=SAMPLE_VENUE_SLUG).delete()
            SubscriptionPlan.objects.filter(name=SAMPLE_PLAN_NAME).delete()
            self.stdout.write(self.style.SUCCESS(f"Cleared sample venue (rows removed: {deleted})."))
            return

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
                slug=SAMPLE_VENUE_SLUG,
                defaults={
                    "owner": owner,
                    "name": SAMPLE_VENUE_NAME,
                    "city": "تهران",
                    "venue_type": VenueType.CAFE,
                    "address": "خیابان ولیعصر — نمونه تست توسعه",
                    "description": "این کافه صرفاً داده نمونه توسعه برای آزمایش نمایشگر ۳۶۰ درجه است.",
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
                activate_subscription(venue, plan=plan, activated_by=admin, note="DEV-ONLY seed")

            space, _ = Space.objects.get_or_create(
                venue=venue,
                name="سالن اصلی — نمونه",
                defaults={"display_order": 1, "is_active": True},
            )

            if not space.active_panorama or space.active_panorama.status != PanoramaStatus.READY:
                webp_bytes, thumb_bytes, file_size = _build_synthetic_equirectangular_webp()
                pano = PanoramaImage.objects.create(
                    space=space,
                    status=PanoramaStatus.READY,
                    width=4096,
                    height=2048,
                    file_size_bytes=file_size,
                )
                pano.webp_file.save("dev_sample_4096x2048.webp", ContentFile(webp_bytes), save=False)
                pano.thumb_file.save("dev_sample_thumb.webp", ContentFile(thumb_bytes), save=False)
                pano.save()
                space.active_panorama = pano
                space.save(update_fields=["active_panorama", "updated_at"])
            else:
                pano = space.active_panorama

            sample_pins = [
                ("میز ۱ (پنجره)", 2, -8.0, 0.0, 50_000, False),
                ("میز ۲ (مرکز)", 4, -12.0, 75.0, 80_000, False),
                ("میز ۳ (تراس)", 4, -6.0, -110.0, 120_000, True),
                ("میز ۴ (VIP)", 6, -10.0, 165.0, 200_000, True),
            ]
            for table_number, capacity, pitch, yaw, fee, is_smoking in sample_pins:
                TablePin.objects.update_or_create(
                    venue=venue,
                    table_number=table_number,
                    defaults={
                        "space": space,
                        "panorama_image": pano,
                        "capacity": capacity,
                        "pitch": pitch,
                        "yaw": yaw,
                        "reservation_fee_toman": fee,
                        "is_smoking": is_smoking,
                        "is_active": True,
                    },
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded DEV-ONLY venue '{venue.name}' (slug={venue.slug}), "
                f"space_id={space.id}, pano={pano.width}x{pano.height} "
                f"({pano.file_size_bytes} bytes), pins={space.table_pins.count()}"
            )
        )
