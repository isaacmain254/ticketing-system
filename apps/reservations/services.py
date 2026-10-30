from django.db import transaction
from django.utils import timezone

from apps.events.models import Event, TicketType
from .constants import RESERVATION_LIFETIME
from .exceptions import (
    InsufficientInventory,
    InvalidReservationQuantity,
    InvalidReservationTransition,
    ReservationNotFound,
    ReservationOwnershipDenied,
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


def _can_manage_reservation(actor, reservation):
    if getattr(actor, 'role', None) == 'STAFF':
        return True
    return reservation.customer_id == actor.id


def _lock_reservation_and_ticket_type(reservation_id):
    try:
        reservation = Reservation.objects.select_for_update().select_related(
            'ticket_type'
        ).get(pk=reservation_id)
    except Reservation.DoesNotExist:
        raise ReservationNotFound('Reservation not found.') from None

    ticket_type = (
        TicketType.objects.select_for_update()
        .select_related('event')
        .get(pk=reservation.ticket_type_id)
    )
    return reservation, ticket_type


@transaction.atomic
def confirm_reservation(customer, reservation_id):
    reservation, ticket_type = _lock_reservation_and_ticket_type(reservation_id)
    if not _can_manage_reservation(customer, reservation):
        raise ReservationOwnershipDenied('Reservation access denied.')

    if reservation.status == Reservation.Status.CONFIRMED:
        return reservation
    if reservation.status != Reservation.Status.PENDING:
        raise InvalidReservationTransition(
            f'Reservation cannot be confirmed from {reservation.status} state.'
        )

    now = timezone.now()
    if reservation.expires_at <= now:
        reservation.status = Reservation.Status.EXPIRED
        reservation.confirmed_at = None
        reservation.save(update_fields=('status', 'confirmed_at', 'updated_at'))

        ticket_type.reserved_quantity -= reservation.quantity
        ticket_type.save(update_fields=('reserved_quantity', 'updated_at'))
        InventoryMovement.objects.create(
            ticket_type=ticket_type,
            reservation=reservation,
            movement_type=InventoryMovement.MovementType.RELEASE,
            quantity=reservation.quantity,
            metadata={'reason': 'expired_during_confirmation'},
        )
        reservation.was_expired_during_confirmation = True
        return reservation

    ticket_type.reserved_quantity -= reservation.quantity
    ticket_type.sold_quantity += reservation.quantity
    ticket_type.save(update_fields=('reserved_quantity', 'sold_quantity', 'updated_at'))

    reservation.status = Reservation.Status.CONFIRMED
    reservation.confirmed_at = now
    reservation.save(
        update_fields=('status', 'confirmed_at', 'updated_at')
    )
    InventoryMovement.objects.create(
        ticket_type=ticket_type,
        reservation=reservation,
        movement_type=InventoryMovement.MovementType.SALE,
        quantity=reservation.quantity,
        metadata={'reason': 'reservation_confirmed'},
    )
    return reservation


@transaction.atomic
def cancel_reservation(customer, reservation_id):
    reservation, ticket_type = _lock_reservation_and_ticket_type(reservation_id)
    if not _can_manage_reservation(customer, reservation):
        raise ReservationOwnershipDenied('Reservation access denied.')

    if reservation.status == Reservation.Status.CANCELLED:
        return reservation
    if reservation.status != Reservation.Status.PENDING:
        raise InvalidReservationTransition(
            f'Reservation cannot be cancelled from {reservation.status} state.'
        )

    ticket_type.reserved_quantity -= reservation.quantity
    ticket_type.save(update_fields=('reserved_quantity', 'updated_at'))

    reservation.status = Reservation.Status.CANCELLED
    reservation.save(update_fields=('status', 'updated_at'))
    InventoryMovement.objects.create(
        ticket_type=ticket_type,
        reservation=reservation,
        movement_type=InventoryMovement.MovementType.RELEASE,
        quantity=reservation.quantity,
        metadata={'reason': 'reservation_cancelled'},
    )
    return reservation
