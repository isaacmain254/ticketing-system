from django.contrib import admin

from .models import InventoryMovement, Reservation


@admin.register(Reservation)
class ReservationAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'customer',
        'ticket_type',
        'quantity',
        'status',
        'expires_at',
    )
    list_filter = ('status',)
    search_fields = ('customer__username', 'ticket_type__name')
    ordering = ('-created_at',)


@admin.register(InventoryMovement)
class InventoryMovementAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'ticket_type',
        'reservation',
        'movement_type',
        'quantity',
        'created_at',
    )
    list_filter = ('movement_type',)
    ordering = ('-created_at',)
