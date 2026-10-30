from django.db import transaction
from django.utils import timezone

from apps.events.models import Event, TicketType
from .constants import RESERVATION_LIFETIME
from .exceptions import (
    InsufficientInventory,
    InvalidReservationQuantity,
    TicketTypeNotAvailable,
)
from .models import InventoryMovement, Reservation


@transaction.atomic
def create_reservation(customer, ticket_type_id, quantity):
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
        raise InvalidReservationQuantity('Quantity must be a positive integer.')

    try:
        ticket_type = (
            TicketType.objects.select_for_update()
            .select_related('event')
            .get(pk=ticket_type_id)
        )
    except TicketType.DoesNotExist:
        raise TicketTypeNotAvailable('Ticket type is not available.') from None

    if ticket_type.event.status != Event.Status.PUBLISHED:
        raise TicketTypeNotAvailable('Ticket type is not available.')

    available = ticket_type.capacity - (
        ticket_type.reserved_quantity + ticket_type.sold_quantity
    )
    if quantity > available:
        raise InsufficientInventory('Not enough ticket inventory available.')

    ticket_type.reserved_quantity += quantity
    ticket_type.save(update_fields=('reserved_quantity', 'updated_at'))

    reservation = Reservation.objects.create(
        customer=customer,
        ticket_type=ticket_type,
        quantity=quantity,
        unit_price=ticket_type.price,
        status=Reservation.Status.PENDING,
        expires_at=timezone.now() + RESERVATION_LIFETIME,
    )

    InventoryMovement.objects.create(
        ticket_type=ticket_type,
        reservation=reservation,
        movement_type=InventoryMovement.MovementType.HOLD,
        quantity=quantity,
        metadata={'reason': 'reservation_created'},
    )

    return reservation
