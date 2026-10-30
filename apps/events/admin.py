from django.contrib import admin

from .models import Event, TicketType


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ('name', 'venue', 'status', 'starts_at')
    list_filter = ('status',)
    search_fields = ('name', 'venue')
    ordering = ('starts_at',)


@admin.register(TicketType)
class TicketTypeAdmin(admin.ModelAdmin):
    list_display = (
        'name',
        'event',
        'price',
        'capacity',
        'reserved_quantity',
        'sold_quantity',
    )
    search_fields = ('name', 'event__name')
