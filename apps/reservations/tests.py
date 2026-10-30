from decimal import Decimal
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

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


class ReservationOwnershipAPITests(APITestCase):
    def setUp(self):
        self.customer = get_user_model().objects.create_user(
            username='customer-one',
            password='C0mpl3x!Passphrase',
        )
        self.other_customer = get_user_model().objects.create_user(
            username='customer-two',
            password='C0mpl3x!Passphrase',
        )
        self.staff = get_user_model().objects.create_user(
            username='staff-one',
            password='C0mpl3x!Passphrase',
            role=get_user_model().Role.STAFF,
        )
        event = Event.objects.create(
            name='Ownership Event',
            venue='Main Hall',
            starts_at=timezone.now() + timedelta(days=1),
            status=Event.Status.PUBLISHED,
        )
        ticket_type = TicketType.objects.create(
            event=event,
            name='General',
            price=Decimal('40.00'),
            capacity=50,
        )
        self.reservation = Reservation.objects.create(
            customer=self.customer,
            ticket_type=ticket_type,
            quantity=2,
            unit_price=ticket_type.price,
            expires_at=timezone.now() + timedelta(minutes=10),
        )

    def test_anonymous_cannot_list_reservations(self):
        response = self.client.get('/api/reservations/')

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_customer_list_is_scoped_to_owner(self):
        Reservation.objects.create(
            customer=self.other_customer,
            ticket_type=self.reservation.ticket_type,
            quantity=1,
            unit_price=self.reservation.unit_price,
            expires_at=timezone.now() + timedelta(minutes=10),
        )
        self.client.force_authenticate(self.customer)

        response = self.client.get('/api/reservations/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)
        self.assertEqual(response.data['results'][0]['id'], str(self.reservation.id))

    def test_customer_cannot_retrieve_another_customer_reservation(self):
        other_reservation = Reservation.objects.create(
            customer=self.other_customer,
            ticket_type=self.reservation.ticket_type,
            quantity=1,
            unit_price=self.reservation.unit_price,
            expires_at=timezone.now() + timedelta(minutes=10),
        )
        self.client.force_authenticate(self.customer)

        response = self.client.get(f'/api/reservations/{other_reservation.id}/')

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_customer_can_retrieve_owned_reservation(self):
        self.client.force_authenticate(self.customer)

        response = self.client.get(f'/api/reservations/{self.reservation.id}/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['id'], str(self.reservation.id))

    def test_staff_can_list_all_reservations(self):
        Reservation.objects.create(
            customer=self.other_customer,
            ticket_type=self.reservation.ticket_type,
            quantity=1,
            unit_price=self.reservation.unit_price,
            expires_at=timezone.now() + timedelta(minutes=10),
        )
        self.client.force_authenticate(self.staff)

        response = self.client.get('/api/reservations/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 2)
