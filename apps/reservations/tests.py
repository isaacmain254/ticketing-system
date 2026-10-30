from decimal import Decimal
from datetime import timedelta
import threading

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db import close_old_connections
from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.events.models import Event, TicketType
from .exceptions import InsufficientInventory, InvalidReservationQuantity, TicketTypeNotAvailable
from .models import InventoryMovement, Reservation
from .services import create_reservation


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


class ReservationCreationServiceTests(APITestCase):
    def setUp(self):
        self.customer = get_user_model().objects.create_user(
            username='creator',
            password='C0mpl3x!Passphrase',
        )
        self.event = Event.objects.create(
            name='Creation Event',
            venue='Arena',
            starts_at=timezone.now() + timedelta(days=1),
            status=Event.Status.PUBLISHED,
        )
        self.ticket_type = TicketType.objects.create(
            event=self.event,
            name='General',
            price=Decimal('75.00'),
            capacity=5,
        )

    def test_successful_creation_updates_all_inventory_records(self):
        reservation = create_reservation(
            self.customer,
            self.ticket_type.id,
            3,
        )

        self.ticket_type.refresh_from_db()
        self.assertEqual(self.ticket_type.reserved_quantity, 3)
        self.assertEqual(reservation.quantity, 3)
        self.assertEqual(reservation.unit_price, Decimal('75.00'))
        self.assertEqual(reservation.status, Reservation.Status.PENDING)
        self.assertEqual(
            InventoryMovement.objects.filter(reservation=reservation).count(),
            1,
        )
        movement = InventoryMovement.objects.get(reservation=reservation)
        self.assertEqual(movement.movement_type, InventoryMovement.MovementType.HOLD)
        self.assertEqual(movement.quantity, 3)

    def test_insufficient_inventory_is_atomic(self):
        with self.assertRaises(InsufficientInventory):
            create_reservation(self.customer, self.ticket_type.id, 6)

        self.ticket_type.refresh_from_db()
        self.assertEqual(self.ticket_type.reserved_quantity, 0)
        self.assertFalse(Reservation.objects.exists())
        self.assertFalse(InventoryMovement.objects.exists())

    def test_invalid_quantity_is_rejected(self):
        for quantity in (0, -1, True, 1.5):
            with self.subTest(quantity=quantity):
                with self.assertRaises(InvalidReservationQuantity):
                    create_reservation(self.customer, self.ticket_type.id, quantity)

        self.assertFalse(Reservation.objects.exists())

    def test_unpublished_event_is_not_available(self):
        self.event.status = Event.Status.DRAFT
        self.event.save(update_fields=('status',))

        with self.assertRaises(TicketTypeNotAvailable):
            create_reservation(self.customer, self.ticket_type.id, 1)

        self.ticket_type.refresh_from_db()
        self.assertEqual(self.ticket_type.reserved_quantity, 0)

    def test_price_snapshot_survives_ticket_price_change(self):
        reservation = create_reservation(
            self.customer,
            self.ticket_type.id,
            1,
        )
        self.ticket_type.price = Decimal('99.00')
        self.ticket_type.save(update_fields=('price',))

        reservation.refresh_from_db()
        self.assertEqual(reservation.unit_price, Decimal('75.00'))

    def test_creation_api_uses_authenticated_customer_and_server_fields(self):
        self.client.force_authenticate(self.customer)

        response = self.client.post(
            '/api/reservations/',
            {
                'ticket_type': str(self.ticket_type.id),
                'quantity': 2,
                'customer': '1',
                'status': 'CONFIRMED',
                'unit_price': '1.00',
                'expires_at': '2000-01-01T00:00:00Z',
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        reservation = Reservation.objects.get(pk=response.data['id'])
        self.assertEqual(reservation.customer, self.customer)
        self.assertEqual(reservation.status, Reservation.Status.PENDING)
        self.assertEqual(reservation.unit_price, Decimal('75.00'))

    def test_creation_api_returns_conflict_when_capacity_is_insufficient(self):
        self.client.force_authenticate(self.customer)

        response = self.client.post(
            '/api/reservations/',
            {'ticket_type': str(self.ticket_type.id), 'quantity': 6},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.ticket_type.refresh_from_db()
        self.assertEqual(self.ticket_type.reserved_quantity, 0)
        self.assertFalse(Reservation.objects.exists())


class ReservationCreationConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.customer_one = get_user_model().objects.create_user(
            username='concurrent-one',
            password='C0mpl3x!Passphrase',
        )
        self.customer_two = get_user_model().objects.create_user(
            username='concurrent-two',
            password='C0mpl3x!Passphrase',
        )
        event = Event.objects.create(
            name='Concurrent Event',
            venue='Arena',
            starts_at=timezone.now() + timedelta(days=1),
            status=Event.Status.PUBLISHED,
        )
        self.ticket_type = TicketType.objects.create(
            event=event,
            name='Last Ticket',
            price=Decimal('50.00'),
            capacity=1,
        )

    def test_two_concurrent_requests_cannot_oversell_last_ticket(self):
        barrier = threading.Barrier(2)
        results = []
        errors = []

        def reserve(customer):
            close_old_connections()
            barrier.wait(timeout=10)
            try:
                create_reservation(customer, self.ticket_type.id, 1)
                results.append('success')
            except InsufficientInventory:
                results.append('insufficient')
            except Exception as exc:
                errors.append(exc)
            finally:
                close_old_connections()

        threads = [
            threading.Thread(
                target=reserve,
                args=(self.customer_one,),
            ),
            threading.Thread(
                target=reserve,
                args=(self.customer_two,),
            ),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(errors, [])
        self.assertEqual(sorted(results), ['insufficient', 'success'])
        self.assertEqual(
            Reservation.objects.filter(status=Reservation.Status.PENDING).count(),
            1,
        )
        self.ticket_type.refresh_from_db()
        self.assertEqual(self.ticket_type.reserved_quantity, 1)
