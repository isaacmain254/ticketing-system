from decimal import Decimal
from datetime import timedelta
import threading

import io

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db import close_old_connections
from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.events.models import Event, TicketType
from .exceptions import (
    InsufficientInventory,
    InvalidReservationQuantity,
    InvalidReservationTransition,
    ReservationOwnershipDenied,
    TicketTypeNotAvailable,
)
from .models import InventoryMovement, Reservation
from .services import (
    cancel_reservation,
    confirm_reservation,
    create_reservation,
    expire_reservation,
)


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
        movement = InventoryMovement.objects.get(
            reservation=reservation,
            movement_type=InventoryMovement.MovementType.HOLD,
        )
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


class ReservationTransitionTests(APITestCase):
    def setUp(self):
        self.customer = get_user_model().objects.create_user(
            username='transition-owner',
            password='C0mpl3x!Passphrase',
        )
        self.other_customer = get_user_model().objects.create_user(
            username='transition-other',
            password='C0mpl3x!Passphrase',
        )
        self.staff = get_user_model().objects.create_user(
            username='transition-staff',
            password='C0mpl3x!Passphrase',
            role=get_user_model().Role.STAFF,
        )
        event = Event.objects.create(
            name='Transition Event',
            venue='Arena',
            starts_at=timezone.now() + timedelta(days=1),
            status=Event.Status.PUBLISHED,
        )
        self.ticket_type = TicketType.objects.create(
            event=event,
            name='General',
            price=Decimal('60.00'),
            capacity=10,
        )
        self.reservation = create_reservation(
            self.customer,
            self.ticket_type.id,
            3,
        )

    def test_confirmation_moves_inventory_and_creates_sale(self):
        reservation = confirm_reservation(
            self.customer,
            self.reservation.id,
        )

        self.ticket_type.refresh_from_db()
        self.reservation.refresh_from_db()
        reservation.refresh_from_db()
        self.assertEqual(reservation.status, Reservation.Status.CONFIRMED)
        self.assertIsNotNone(reservation.confirmed_at)
        self.assertEqual(self.ticket_type.reserved_quantity, 0)
        self.assertEqual(self.ticket_type.sold_quantity, 3)
        movement = InventoryMovement.objects.get(
            reservation=reservation,
            movement_type=InventoryMovement.MovementType.SALE,
        )
        self.assertEqual(movement.movement_type, InventoryMovement.MovementType.SALE)
        self.assertEqual(movement.quantity, 3)

    def test_repeated_confirmation_is_idempotent(self):
        confirm_reservation(self.customer, self.reservation.id)
        confirm_reservation(self.customer, self.reservation.id)

        self.ticket_type.refresh_from_db()
        self.assertEqual(self.ticket_type.reserved_quantity, 0)
        self.assertEqual(self.ticket_type.sold_quantity, 3)
        self.assertEqual(
            InventoryMovement.objects.filter(
                reservation=self.reservation,
                movement_type=InventoryMovement.MovementType.SALE,
            ).count(),
            1,
        )

    def test_cancellation_releases_inventory_and_creates_release(self):
        reservation = cancel_reservation(
            self.customer,
            self.reservation.id,
        )

        self.ticket_type.refresh_from_db()
        self.assertEqual(reservation.status, Reservation.Status.CANCELLED)
        self.assertEqual(self.ticket_type.reserved_quantity, 0)
        self.assertEqual(self.ticket_type.sold_quantity, 0)
        movement = InventoryMovement.objects.filter(
            reservation=reservation,
            movement_type=InventoryMovement.MovementType.RELEASE,
        ).get()
        self.assertEqual(movement.quantity, 3)

    def test_repeated_cancellation_is_idempotent(self):
        cancel_reservation(self.customer, self.reservation.id)
        cancel_reservation(self.customer, self.reservation.id)

        self.ticket_type.refresh_from_db()
        self.assertEqual(self.ticket_type.reserved_quantity, 0)
        self.assertEqual(
            InventoryMovement.objects.filter(
                reservation=self.reservation,
                movement_type=InventoryMovement.MovementType.RELEASE,
            ).count(),
            1,
        )

    def test_confirmation_after_deadline_expires_and_releases_hold(self):
        self.reservation.expires_at = timezone.now() - timedelta(seconds=1)
        self.reservation.save(update_fields=('expires_at',))

        reservation = confirm_reservation(
            self.customer,
            self.reservation.id,
        )

        self.reservation.refresh_from_db()
        self.ticket_type.refresh_from_db()
        self.assertEqual(reservation.status, Reservation.Status.EXPIRED)
        self.assertEqual(self.ticket_type.reserved_quantity, 0)
        self.assertEqual(self.ticket_type.sold_quantity, 0)
        movement = InventoryMovement.objects.get(
            reservation=self.reservation,
            movement_type=InventoryMovement.MovementType.RELEASE,
        )
        self.assertEqual(movement.quantity, 3)

    def test_confirming_expired_reservation_is_rejected(self):
        self.reservation.expires_at = timezone.now() - timedelta(seconds=1)
        self.reservation.save(update_fields=('expires_at',))
        confirm_reservation(self.customer, self.reservation.id)

        with self.assertRaises(InvalidReservationTransition):
            confirm_reservation(self.customer, self.reservation.id)

    def test_confirmed_reservation_cannot_be_cancelled(self):
        confirm_reservation(self.customer, self.reservation.id)

        with self.assertRaises(InvalidReservationTransition):
            cancel_reservation(self.customer, self.reservation.id)

    def test_other_customer_cannot_transition_reservation(self):
        with self.assertRaises(ReservationOwnershipDenied):
            confirm_reservation(
                self.other_customer,
                self.reservation.id,
            )

        self.reservation.refresh_from_db()
        self.assertEqual(self.reservation.status, Reservation.Status.PENDING)

    def test_confirm_api_returns_conflict_for_past_deadline(self):
        self.reservation.expires_at = timezone.now() - timedelta(seconds=1)
        self.reservation.save(update_fields=('expires_at',))
        self.client.force_authenticate(self.customer)

        response = self.client.post(
            f'/api/reservations/{self.reservation.id}/confirm/'
        )

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.reservation.refresh_from_db()
        self.ticket_type.refresh_from_db()
        self.assertEqual(self.reservation.status, Reservation.Status.EXPIRED)
        self.assertEqual(self.ticket_type.reserved_quantity, 0)

    def test_cancel_api_is_idempotent(self):
        self.client.force_authenticate(self.customer)

        first = self.client.post(
            f'/api/reservations/{self.reservation.id}/cancel/'
        )
        second = self.client.post(
            f'/api/reservations/{self.reservation.id}/cancel/'
        )

        self.assertEqual(first.status_code, status.HTTP_200_OK)
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        self.ticket_type.refresh_from_db()
        self.assertEqual(self.ticket_type.reserved_quantity, 0)
        self.assertEqual(
            InventoryMovement.objects.filter(
                reservation=self.reservation,
                movement_type=InventoryMovement.MovementType.RELEASE,
            ).count(),
            1,
        )

    def test_staff_may_transition_reservation(self):
        reservation = confirm_reservation(
            self.staff,
            self.reservation.id,
        )

        self.assertEqual(reservation.status, Reservation.Status.CONFIRMED)


class ReservationExpiryCommandTests(APITestCase):
    def setUp(self):
        self.customer = get_user_model().objects.create_user(
            username='expiry-owner',
            password='C0mpl3x!Passphrase',
        )
        event = Event.objects.create(
            name='Expiry Event',
            venue='Arena',
            starts_at=timezone.now() + timedelta(days=1),
            status=Event.Status.PUBLISHED,
        )
        self.ticket_type = TicketType.objects.create(
            event=event,
            name='General',
            price=Decimal('40.00'),
            capacity=10,
        )
        self.reservation = create_reservation(
            self.customer,
            self.ticket_type.id,
            3,
        )

    def run_expiry_command(self, *args):
        output = io.StringIO()
        call_command('expire_reservations', *args, stdout=output)
        return output.getvalue()

    def test_command_expires_past_deadline_and_releases_once(self):
        self.reservation.expires_at = timezone.now() - timedelta(seconds=1)
        self.reservation.save(update_fields=('expires_at',))

        self.run_expiry_command()
        self.run_expiry_command()

        self.reservation.refresh_from_db()
        self.ticket_type.refresh_from_db()
        self.assertEqual(self.reservation.status, Reservation.Status.EXPIRED)
        self.assertEqual(self.ticket_type.reserved_quantity, 0)
        self.assertEqual(
            InventoryMovement.objects.filter(
                reservation=self.reservation,
                movement_type=InventoryMovement.MovementType.RELEASE,
            ).count(),
            1,
        )

    def test_command_does_not_expire_future_deadline(self):
        output = self.run_expiry_command()

        self.reservation.refresh_from_db()
        self.ticket_type.refresh_from_db()
        self.assertEqual(self.reservation.status, Reservation.Status.PENDING)
        self.assertEqual(self.ticket_type.reserved_quantity, 3)
        self.assertIn('Expired 0 reservation(s).', output)

    def test_batch_size_limits_processed_reservations(self):
        self.reservation.expires_at = timezone.now() - timedelta(seconds=1)
        self.reservation.save(update_fields=('expires_at',))
        second = create_reservation(
            self.customer,
            self.ticket_type.id,
            1,
        )
        second.expires_at = timezone.now() - timedelta(seconds=2)
        second.save(update_fields=('expires_at',))

        output = self.run_expiry_command('--batch-size', '1')

        self.assertIn('Expired 1 reservation(s).', output)
        expired_count = Reservation.objects.filter(
            status=Reservation.Status.EXPIRED
        ).count()
        self.assertEqual(expired_count, 1)

    def test_negative_batch_size_is_rejected(self):
        with self.assertRaises(CommandError):
            self.run_expiry_command('--batch-size', '-1')

    def test_confirmation_wins_race(self):
        confirmed = confirm_reservation(
            self.customer,
            self.reservation.id,
        )
        expired = expire_reservation(self.reservation.id)

        self.reservation.refresh_from_db()
        self.ticket_type.refresh_from_db()
        self.assertEqual(confirmed.status, Reservation.Status.CONFIRMED)
        self.assertFalse(expired)
        self.assertEqual(self.reservation.status, Reservation.Status.CONFIRMED)
        self.assertEqual(self.ticket_type.reserved_quantity, 0)
        self.assertEqual(self.ticket_type.sold_quantity, 3)
