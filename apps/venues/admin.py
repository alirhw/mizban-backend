"""Venue catalogue admin (task T-008 registrations).

Model administration only: the approve/reject workflow for platform
admins (FR-012) and owner-side operations land in T-009 - approving a
venue here is just the ``is_approved`` field until then.
"""
from django.contrib import admin

from .models import DesignAddon, OperatingHours, Subscription, Venue


@admin.register(Venue)
class VenueAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "city",
        "venue_type",
        "owner",
        "is_approved",
        "subscription_status",
    )
    list_filter = ("city", "venue_type", "is_approved", "subscription_status")
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(OperatingHours)
class OperatingHoursAdmin(admin.ModelAdmin):
    list_display = ("venue", "weekday", "open_time", "close_time")
    list_filter = ("weekday",)


@admin.register(DesignAddon)
class DesignAddonAdmin(admin.ModelAdmin):
    list_display = ("title", "venue", "fee", "is_active")
    list_filter = ("is_active",)
    search_fields = ("title",)


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ("venue", "plan_name", "status", "started_at", "expires_at")
    list_filter = ("status",)
