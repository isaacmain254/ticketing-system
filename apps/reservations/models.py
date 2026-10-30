import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class Reservation(models.Model):
    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        CONFIRMED = 'CONFIRMED', 'Confirmed'
        CANCELLED = 'CANCELLED', 'Cancelled'
        EXPIRED = 'EXPIRED', 'Expired'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='reservations',
    )
    ticket_type = models.ForeignKey(
        'events.TicketType',
        on_delete=models.PROTECT,
        related_name='reservations',
    )
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    expires_at = models.DateTimeField()
    confirmed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('-created_at', '-id')
        indexes = [
            models.Index(
                fields=('status', 'expires_at'),
                name='reservation_status_expiry_idx',
            ),
            models.Index(
                fields=('customer', 'created_at'),
                name='reservation_customer_created',
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0),
                name='reservation_quantity_positive',
            ),
            models.CheckConstraint(
                condition=models.Q(unit_price__gte=0),
                name='reservation_unit_price_nonnegative',
            ),
        ]

    @property
    def total_price(self):
        return self.unit_price * self.quantity

    def clean(self) -> None:
        super().clean()
        if self.confirmed_at is not None and self.status != self.Status.CONFIRMED:
            raise ValidationError({
                'confirmed_at': 'Confirmed timestamp is only valid for confirmed reservations.',
            })
        if self.status == self.Status.CONFIRMED and self.confirmed_at is None:
            raise ValidationError({
                'confirmed_at': 'Confirmed reservations must have a confirmed timestamp.',
            })

    def __str__(self) -> str:
        return f'{self.id} - {self.status}'


class InventoryMovement(models.Model):
    class MovementType(models.TextChoices):
        HOLD = 'HOLD', 'Hold'
        RELEASE = 'RELEASE', 'Release'
        SALE = 'SALE', 'Sale'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ticket_type = models.ForeignKey(
        'events.TicketType',
        on_delete=models.PROTECT,
        related_name='inventory_movements',
    )
    reservation = models.ForeignKey(
        Reservation,
        on_delete=models.PROTECT,
        related_name='inventory_movements',
    )
    movement_type = models.CharField(
        max_length=10,
        choices=MovementType.choices,
        db_index=True,
    )
    quantity = models.PositiveIntegerField()
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('created_at', 'id')
        indexes = [
            models.Index(
                fields=('ticket_type', 'created_at'),
                name='movement_ticket_created_idx',
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0),
                name='movement_quantity_positive',
            ),
        ]

    def __str__(self) -> str:
        return f'{self.movement_type} {self.quantity}'
