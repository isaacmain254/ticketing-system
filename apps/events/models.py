import uuid

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


class Event(models.Model):
    class Status(models.TextChoices):
        DRAFT = 'DRAFT', 'Draft'
        PUBLISHED = 'PUBLISHED', 'Published'
        CANCELLED = 'CANCELLED', 'Cancelled'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    venue = models.CharField(max_length=200)
    starts_at = models.DateTimeField()
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('starts_at', 'name')

    def __str__(self) -> str:
        return self.name


class TicketType(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event = models.ForeignKey(
        Event,
        on_delete=models.PROTECT,
        related_name='ticket_types',
    )
    name = models.CharField(max_length=200)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    capacity = models.PositiveIntegerField()
    reserved_quantity = models.PositiveIntegerField(default=0)
    sold_quantity = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('name',)
        constraints = [
            models.UniqueConstraint(
                fields=('event', 'name'),
                name='unique_ticket_type_per_event',
            ),
            models.CheckConstraint(
                condition=Q(price__gte=0),
                name='ticket_type_price_nonnegative',
            ),
            models.CheckConstraint(
                condition=Q(capacity__gte=0),
                name='ticket_type_capacity_nonnegative',
            ),
            models.CheckConstraint(
                condition=Q(reserved_quantity__gte=0),
                name='ticket_type_reserved_nonnegative',
            ),
            models.CheckConstraint(
                condition=Q(sold_quantity__gte=0),
                name='ticket_type_sold_nonnegative',
            ),
            models.CheckConstraint(
                condition=Q(reserved_quantity__gte=0)
                & Q(sold_quantity__gte=0)
                & Q(capacity__gte=models.F('reserved_quantity') + models.F('sold_quantity')),
                name='ticket_type_inventory_within_capacity',
            ),
        ]

    def clean(self) -> None:
        super().clean()
        if self.capacity is not None and (
            self.reserved_quantity + self.sold_quantity > self.capacity
        ):
            raise ValidationError({
                'capacity': 'Capacity cannot be less than reserved plus sold quantity.',
            })

    @property
    def availability(self) -> int:
        return self.capacity - self.reserved_quantity - self.sold_quantity

    def __str__(self) -> str:
        return f'{self.name} ({self.event.name})'
