"""Venue catalogue admin (Task T-009 enhanced with approval actions & cache invalidation)."""
from django.contrib import admin
from django.db import transaction

from .models import DesignAddon, OperatingHours, Subscription, Venue
from .services import invalidate_venue_cache


@admin.register(Venue)
class VenueAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "city",
        "venue_type",
        "owner",
        "is_approved",
        "subscription_status",
        "created_at",
    )
    list_filter = ("city", "venue_type", "is_approved", "subscription_status")
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}
    actions = ["approve_selected_venues", "reject_selected_venues"]

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        vid, vslug = obj.id, obj.slug
        transaction.on_commit(lambda: invalidate_venue_cache(vid, vslug))

    def delete_model(self, request, obj):
        vid, vslug = obj.id, obj.slug
        super().delete_model(request, obj)
        transaction.on_commit(lambda: invalidate_venue_cache(vid, vslug))

    @admin.action(description="Approve selected venues (is_approved=True)")
    def approve_selected_venues(self, request, queryset):
        for venue in queryset:
            venue.is_approved = True
            venue.save(update_fields=["is_approved", "updated_at"])
            vid, vslug = venue.id, venue.slug
            transaction.on_commit(lambda: invalidate_venue_cache(vid, vslug))
        self.message_user(request, f"{queryset.count()} venue(s) approved.")

    @admin.action(description="Reject selected venues (is_approved=False)")
    def reject_selected_venues(self, request, queryset):
        for venue in queryset:
            venue.is_approved = False
            venue.save(update_fields=["is_approved", "updated_at"])
            vid, vslug = venue.id, venue.slug
            transaction.on_commit(lambda: invalidate_venue_cache(vid, vslug))
        self.message_user(request, f"{queryset.count()} venue(s) rejected.")


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
