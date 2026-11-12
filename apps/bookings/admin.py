"""Django Admin registration for Booking and BookingAddon (Task T-011)."""
from django.contrib import admin

from apps.bookings.models import Booking, BookingAddon


class BookingAddonInline(admin.TabularInline):
    model = BookingAddon
    extra = 0
    readonly_fields = ["design_addon", "price_snapshot_toman", "created_at"]


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "venue",
        "table_pin",
        "customer",
        "status",
        "jalali_date",
        "jalali_start_datetime",
        "amount_online_toman",
        "amount_in_person_toman",
    ]
    list_filter = ["status", "venue", "slot_date"]
    search_fields = ["id", "customer__phone", "venue__name", "table_pin__table_number"]
    readonly_fields = [
        "created_at",
        "updated_at",
        "jalali_date",
        "jalali_start_datetime",
        "jalali_end_datetime",
    ]
    inlines = [BookingAddonInline]


@admin.register(BookingAddon)
class BookingAddonAdmin(admin.ModelAdmin):
    list_display = ["id", "booking", "design_addon", "price_snapshot_toman", "created_at"]
    list_filter = ["design_addon__venue"]
