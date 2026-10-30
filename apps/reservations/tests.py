from decimal import Decimal
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from apps.events.models import Event, TicketType
from .models import InventoryMovement, Reservation


class ReservationModelTests(TestCase):
    def setUp(self):
        self.customer = get_user_model().objects.create_user(
            username='customer',
            password='test-password',
        )
        self.event = Event.objects.create(
            name='Test Event',
            venue='Main Hall',
            starts_at=timezone.now() + timedelta(days=1),
            status=Event.Status.PUBLISHED,
        )
        self.ticket_type = TicketType.objects.create(
            event=self.event,
            name='General',
            price=Decimal('40.00'),
            capacity=50,
        )

    def create_reservation(self):
        return Reservation.objects.create(
            customer=self.customer,
            ticket_type=self.ticket_type,
            quantity=3,
            unit_price=self.ticket_type.price,
            status=Reservation.Status.PENDING,
            expires_at=timezone.now() + timedelta(minutes=10),
        )

    def test_reservation_snapshots_price_and_calculates_total(self):
        reservation = self.create_reservation()
        self.ticket_type.price = Decimal('55.00')
        self.ticket_type.save(update_fields=('price',))

        reservation.refresh_from_db()
        self.assertEqual(reservation.unit_price, Decimal('40.00'))
        self.assertEqual(reservation.total_price, Decimal('120.00'))

    def test_quantity_must_be_positive(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Reservation.objects.create(
                customer=self.customer,
                ticket_type=self.ticket_type,
                quantity=0,
                unit_price=Decimal('40.00'),
                expires_at=timezone.now() + timedelta(minutes=10),
            )

    def test_confirmed_reservation_requires_confirmation_timestamp(self):
        reservation = self.create_reservation()
        reservation.status = Reservation.Status.CONFIRMED

        with self.assertRaises(ValidationError):
            reservation.full_clean()

    def test_movement_quantity_must_be_positive(self):
        reservation = self.create_reservation()

        with self.assertRaises(IntegrityError), transaction.atomic():
            InventoryMovement.objects.create(
                ticket_type=self.ticket_type,
                reservation=reservation,
                movement_type=InventoryMovement.MovementType.HOLD,
                quantity=0,
            )

    def test_customer_cannot_be_deleted_while_reservations_exist(self):
        self.create_reservation()

        with self.assertRaises(IntegrityError), transaction.atomic():
            self.customer.delete()

    def test_reservation_cannot_be_deleted_while_movements_exist(self):
        reservation = self.create_reservation()
        InventoryMovement.objects.create(
            ticket_type=self.ticket_type,
            reservation=reservation,
            movement_type=InventoryMovement.MovementType.HOLD,
            quantity=reservation.quantity,
        )

        with self.assertRaises(IntegrityError), transaction.atomic():
            reservation.delete()
