"""Venue catalogue admin (Task T-009 enhanced with approval actions & cache invalidation)."""
from django import forms
from django.contrib import admin
from django.db import transaction

from .models import (
    DesignAddon,
    OperatingHours,
    SubscriptionPlan,
    Venue,
    VenueSubscription,
)
from .services import activate_subscription, invalidate_venue_cache


@admin.register(Venue)
class VenueAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "city",
        "venue_type",
        "owner",
        "is_approved",
        "has_active_subscription_display",
        "created_at",
    )
    list_filter = ("city", "venue_type", "is_approved")

    @admin.display(boolean=True, description="Subscription active")
    def has_active_subscription_display(self, obj: Venue) -> bool:
        return obj.has_active_subscription()
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


@admin.register(SubscriptionPlan)
class SubscriptionPlanAdmin(admin.ModelAdmin):
    list_display = ("name", "duration_days", "price_toman", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name",)


class VenueSubscriptionAddForm(forms.ModelForm):
    class Meta:
        model = VenueSubscription
        fields = ("venue", "plan", "note")


@admin.register(VenueSubscription)
class VenueSubscriptionAdmin(admin.ModelAdmin):
    """Add-only admin delegating all window computation to activate_subscription."""

    form = VenueSubscriptionAddForm
    list_display = ("venue", "plan", "starts_at", "expires_at", "created_by", "created_at")
    list_filter = ("venue", "plan")
    readonly_fields = ("starts_at", "expires_at", "created_by", "created_at")

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False

    def save_model(self, request, obj, form, change):
        created = activate_subscription(
            venue=form.cleaned_data["venue"],
            plan=form.cleaned_data["plan"],
            activated_by=request.user,
            note=form.cleaned_data.get("note", ""),
        )
        obj.pk = created.pk
        obj.starts_at = created.starts_at
        obj.expires_at = created.expires_at
        obj.created_by = created.created_by
        obj.created_at = created.created_at
