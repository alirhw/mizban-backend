"""Admin registrations for the panoramas app (Space, PanoramaImage, TablePin)."""
from django.contrib import admin

from apps.panoramas.models import PanoramaImage, Space, TablePin


@admin.register(Space)
class SpaceAdmin(admin.ModelAdmin):
    list_display = ["name", "venue", "display_order", "is_active", "active_panorama", "created_at"]
    list_filter = ["is_active", "venue"]
    search_fields = ["name", "venue__name"]


@admin.register(PanoramaImage)
class PanoramaImageAdmin(admin.ModelAdmin):
    list_display = ["id", "space", "status", "width", "height", "created_at", "processed_at"]
    list_filter = ["status", "space__venue"]
    search_fields = ["id", "space__name"]


@admin.register(TablePin)
class TablePinAdmin(admin.ModelAdmin):
    list_display = [
        "table_number",
        "venue",
        "space",
        "capacity",
        "reservation_fee_toman",
        "is_smoking",
        "pitch",
        "yaw",
        "is_active",
    ]
    list_filter = ["is_active", "is_smoking", "venue", "space"]
    search_fields = ["table_number", "venue__name"]
