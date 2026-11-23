"""Domain models for the venues app (task T-008).

Venue catalogue persistence: the venue profile, its weekly operating
hours, its design add-on catalogue and subscription records. No
workflows live here - owner operations, admin approval flows and cache
invalidation land in T-009; slot generation (T-010) consumes
OperatingHours but defines no models of its own here.

Field shapes follow the Chat-04 handoff entity list and section 28
naming conventions. Money is integer Toman (never floats - AGENTS.md).
"""
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from .managers import VenueQuerySet


class VenueType(models.TextChoices):
    CAFE = "CAFE", "Cafe"
    RESTAURANT = "RESTAURANT", "Restaurant"


class SubscriptionStatus(models.TextChoices):
    INACTIVE = "INACTIVE", "Inactive"
    ACTIVE = "ACTIVE", "Active"
    EXPIRED = "EXPIRED", "Expired"


class Venue(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="venues",
    )
    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    city = models.CharField(max_length=100)
    venue_type = models.CharField(max_length=16, choices=VenueType.choices)
    address = models.TextField()
    description = models.TextField(blank=True)
    is_approved = models.BooleanField(
        default=False,
        help_text="Set by a platform admin only (workflow lands in T-009).",
    )
    subscription_status = models.CharField(
        max_length=16,
        choices=SubscriptionStatus.choices,
        default=SubscriptionStatus.INACTIVE,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = VenueQuerySet.as_manager()

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    def has_active_subscription(self, now=None) -> bool:
        """Single read path for BR-005 subscription activity (Decision 5 / T-025)."""
        current_time = now or timezone.now()
        return self.venue_subscriptions.filter(expires_at__gt=current_time).exists()

    @property
    def is_publicly_visible(self) -> bool:
        """BR-005: publicly listed/bookable only when admin-approved
        AND has an active VenueSubscription. Mirrors ``VenueQuerySet.public()``."""
        return self.is_approved and self.has_active_subscription()


class OperatingHours(models.Model):
    """One row per weekday for a venue.

    ``weekday`` follows Python's ``date.weekday()`` convention:
    0=Monday ... 6=Sunday. The scheduling engine (T-010) maps Jalali
    calendar days onto this convention; no Jalali mapping is baked in
    here. Times are local wall-clock times of the venue; converting a
    Jalali date + these times into aware UTC datetimes is also T-010's
    job (ARCH-006: only UTC is ever stored for instants).
    """

    class Weekday(models.IntegerChoices):
        MONDAY = 0, "Monday"
        TUESDAY = 1, "Tuesday"
        WEDNESDAY = 2, "Wednesday"
        THURSDAY = 3, "Thursday"
        FRIDAY = 4, "Friday"
        SATURDAY = 5, "Saturday"
        SUNDAY = 6, "Sunday"

    venue = models.ForeignKey(
        Venue,
        on_delete=models.CASCADE,
        related_name="operating_hours",
    )
    weekday = models.IntegerField(choices=Weekday.choices)
    open_time = models.TimeField()
    close_time = models.TimeField(
        help_text=(
            "May be earlier than open_time: the venue then closes after "
            "midnight (e.g. open 18:00, close 02:00)."
        ),
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["venue", "weekday"],
                name="unique_operating_hours_venue_weekday",
            ),
        ]
        ordering = ["weekday"]

    def __str__(self) -> str:
        return f"{self.venue} {self.get_weekday_display()} {self.open_time}-{self.close_time}"

    @property
    def crosses_midnight(self) -> bool:
        return self.close_time <= self.open_time


class DesignAddon(models.Model):
    """A decorative add-on a venue offers (flowers, candles, ...).

    ``fee`` is what the customer pays THE VENUE in person (BR-003 /
    ARCH-005): it is printed on the receipt as "payable in person" and
    is never charged through the platform gateway. Stored as integer
    Toman.
    """

    venue = models.ForeignKey(
        Venue,
        on_delete=models.CASCADE,
        related_name="design_addons",
    )
    title = models.CharField(max_length=200)
    fee = models.BigIntegerField(help_text="Price in Toman.")
    image = models.ImageField(upload_to="addons/%Y/%m/", blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(fee__gte=0),
                name="design_addon_fee_non_negative",
            ),
        ]
        ordering = ["title"]

    def __str__(self) -> str:
        return self.title


class Subscription(models.Model):
    """A venue's platform subscription record (model only in T-008).

    Purchase/payment flow and the ACTIVE/EXPIRED lifecycle transitions
    land in later billing tasks (PH-05); this model only persists the
    state those flows will drive.
    """

    venue = models.ForeignKey(
        Venue,
        on_delete=models.CASCADE,
        related_name="subscriptions",
    )
    plan_name = models.CharField(max_length=100)
    status = models.CharField(
        max_length=16,
        choices=SubscriptionStatus.choices,
        default=SubscriptionStatus.INACTIVE,
    )
    started_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.venue} - {self.plan_name} ({self.status})"


class SubscriptionPlan(models.Model):
    """Admin-defined subscription package (Decision 5 / Task T-025).

    No seed plans or hard-coded prices exist; plans are created by admins in Django Admin.
    """

    name = models.CharField(max_length=100, unique=True)
    duration_days = models.PositiveIntegerField(
        help_text="Duration of the subscription window in days (> 0).",
    )
    price_toman = models.BigIntegerField(
        help_text="Plan price in integer Toman (>= 0).",
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Inactive plans cannot be used for new activations.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(duration_days__gt=0),
                name="subscription_plan_duration_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(price_toman__gte=0),
                name="subscription_plan_price_non_negative",
            ),
        ]
        ordering = ["duration_days", "name"]

    def clean(self) -> None:
        super().clean()
        if self.duration_days is not None and self.duration_days <= 0:
            raise ValidationError({"duration_days": "Duration must be greater than zero days."})
        if self.price_toman is not None and self.price_toman < 0:
            raise ValidationError({"price_toman": "Price must be non-negative."})

    def __str__(self) -> str:
        return f"{self.name} ({self.duration_days}d / {self.price_toman} Toman)"


class VenueSubscription(models.Model):
    """Append-only history of manually activated venue subscriptions (Decision 5 / Task T-025)."""

    venue = models.ForeignKey(
        Venue,
        on_delete=models.CASCADE,
        related_name="venue_subscriptions",
    )
    plan = models.ForeignKey(
        SubscriptionPlan,
        on_delete=models.PROTECT,
        related_name="venue_subscriptions",
    )
    starts_at = models.DateTimeField(help_text="Subscription window start in aware UTC.")
    expires_at = models.DateTimeField(db_index=True, help_text="Subscription window expiry in aware UTC.")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="activated_venue_subscriptions",
        help_text="Admin user who activated this subscription.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    note = models.TextField(
        blank=True,
        default="",
        help_text="Optional offline-coordination reference note.",
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(expires_at__gt=models.F("starts_at")),
                name="venue_subscription_expires_after_starts",
            ),
        ]
        indexes = [
            models.Index(fields=["venue", "expires_at"], name="idx_venuesub_venue_expires"),
        ]
        ordering = ["-expires_at", "-created_at"]

    def __str__(self) -> str:
        return f"{self.venue.name} - {self.plan.name} (expires {self.expires_at:%Y-%m-%d})"
