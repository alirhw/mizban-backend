"""Read-only Django Admin registration for BlockedSlot support visibility (Task T-026)."""
from django.contrib import admin

from apps.scheduling.models import BlockedSlot


@admin.register(BlockedSlot)
class BlockedSlotAdmin(admin.ModelAdmin):
    list_display = ("id", "table_pin", "start_at", "end_at", "created_by", "created_at")
    list_filter = ("table_pin__venue",)
    search_fields = ("table_pin__table_number", "reason")
    readonly_fields = ("table_pin", "start_at", "end_at", "reason", "created_by", "created_at")

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False
