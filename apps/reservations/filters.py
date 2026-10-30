import django_filters
from rest_framework.exceptions import ValidationError

from .models import InventoryMovement, Reservation


STATUS_VALUES = (
    ('pending', 'Pending'),
    ('confirmed', 'Confirmed'),
    ('cancelled', 'Cancelled'),
    ('expired', 'Expired'),
)


class ReservationFilterSet(django_filters.FilterSet):
    status = django_filters.ChoiceFilter(
        choices=STATUS_VALUES,
        method='filter_status',
    )
    event_id = django_filters.UUIDFilter(
        field_name='ticket_type__event_id',
    )
    ticket_type = django_filters.UUIDFilter(field_name='ticket_type_id')
    created_after = django_filters.DateTimeFilter(field_name='created_at', lookup_expr='gte')
    created_before = django_filters.DateTimeFilter(field_name='created_at', lookup_expr='lte')
    customer_id = django_filters.NumberFilter(method='filter_customer')

    class Meta:
        model = Reservation
        fields = ('status', 'event_id', 'ticket_type', 'customer_id')

    def filter_status(self, queryset, name, value):
        return queryset.filter(status=value.upper())

    def filter_customer(self, queryset, name, value):
        request = getattr(self, 'request', None)
        if request and getattr(request.user, 'role', None) == 'STAFF':
            return queryset.filter(customer_id=value)
        return queryset

    def filter_queryset(self, queryset):
        cleaned = self.form.cleaned_data
        created_after = cleaned.get('created_after')
        created_before = cleaned.get('created_before')
        if created_after and created_before and created_after > created_before:
            raise ValidationError({
                'created_after': 'created_after must be before or equal to created_before.',
            })
        return super().filter_queryset(queryset)


class InventoryMovementFilterSet(django_filters.FilterSet):
    reservation = django_filters.UUIDFilter(field_name='reservation_id')
    ticket_type = django_filters.UUIDFilter(field_name='ticket_type_id')
    movement_type = django_filters.ChoiceFilter(
        choices=(
            ('hold', 'Hold'),
            ('release', 'Release'),
            ('sale', 'Sale'),
        ),
        method='filter_movement_type',
    )
    created_after = django_filters.DateTimeFilter(field_name='created_at', lookup_expr='gte')
    created_before = django_filters.DateTimeFilter(field_name='created_at', lookup_expr='lte')

    class Meta:
        model = InventoryMovement
        fields = (
            'reservation',
            'ticket_type',
            'movement_type',
            'created_after',
            'created_before',
        )

    def filter_queryset(self, queryset):
        cleaned = self.form.cleaned_data
        created_after = cleaned.get('created_after')
        created_before = cleaned.get('created_before')
        if created_after and created_before and created_after > created_before:
            raise ValidationError({
                'created_after': 'created_after must be before or equal to created_before.',
            })
        return super().filter_queryset(queryset)

    def filter_movement_type(self, queryset, name, value):
        return queryset.filter(movement_type=value.upper())
