from decimal import Decimal
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from .models import Event, TicketType


class EventAndTicketTypeModelTests(TestCase):
    def setUp(self):
        self.event = Event.objects.create(
            name='Python Conference',
            description='A backend engineering conference.',
            venue='Convention Center',
            starts_at=timezone.now() + timedelta(days=30),
            status=Event.Status.PUBLISHED,
        )

    def test_ticket_type_availability(self):
        ticket_type = TicketType.objects.create(
            event=self.event,
            name='General Admission',
            price=Decimal('49.95'),
            capacity=100,
            reserved_quantity=10,
            sold_quantity=20,
        )

        self.assertEqual(ticket_type.availability, 70)

    def test_ticket_type_names_must_be_unique_per_event(self):
        TicketType.objects.create(
            event=self.event,
            name='VIP',
            price=Decimal('100.00'),
            capacity=10,
        )

        with self.assertRaises(IntegrityError), transaction.atomic():
            TicketType.objects.create(
                event=self.event,
                name='VIP',
                price=Decimal('120.00'),
                capacity=10,
            )

    def test_capacity_cannot_be_below_held_and_sold_inventory(self):
        ticket_type = TicketType(
            event=self.event,
            name='Reserved Seat',
            price=Decimal('25.00'),
            capacity=10,
            reserved_quantity=6,
            sold_quantity=5,
        )

        with self.assertRaises(ValidationError):
            ticket_type.full_clean()

    def test_database_rejects_over_capacity_counter_values(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            TicketType.objects.create(
                event=self.event,
                name='Over Capacity',
                price=Decimal('25.00'),
                capacity=10,
                reserved_quantity=6,
                sold_quantity=5,
            )

    def test_database_rejects_negative_price(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            TicketType.objects.create(
                event=self.event,
                name='Invalid Price',
                price=Decimal('-0.01'),
                capacity=10,
            )

    def test_event_cannot_be_deleted_while_ticket_types_exist(self):
        TicketType.objects.create(
            event=self.event,
            name='General Admission',
            price=Decimal('49.95'),
            capacity=100,
        )

        with self.assertRaises(IntegrityError), transaction.atomic():
            self.event.delete()


class Phase6EventAPITests(APITestCase):
    def setUp(self):
        self.customer = get_user_model().objects.create_user(
            username='phase6-customer',
            password='C0mpl3x!Passphrase',
        )
        self.staff = get_user_model().objects.create_user(
            username='phase6-staff',
            password='C0mpl3x!Passphrase',
            role=get_user_model().Role.STAFF,
        )
        self.published = Event.objects.create(
            name='Published Event',
            description='Visible',
            venue='Main Hall',
            starts_at=timezone.now() + timedelta(days=10),
            status=Event.Status.PUBLISHED,
        )
        self.draft = Event.objects.create(
            name='Draft Event',
            venue='Back Hall',
            starts_at=timezone.now() + timedelta(days=20),
            status=Event.Status.DRAFT,
        )
        self.ticket_type = TicketType.objects.create(
            event=self.published,
            name='General',
            price=Decimal('25.00'),
            capacity=20,
        )

    def test_public_event_list_excludes_drafts(self):
        response = self.client.get('/api/v1/events/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        returned_ids = {item['id'] for item in response.data['results']}
        self.assertIn(str(self.published.id), returned_ids)
        self.assertNotIn(str(self.draft.id), returned_ids)

    def test_customer_cannot_create_event(self):
        self.client.force_authenticate(self.customer)

        response = self.client.post('/api/v1/events/', {
            'name': 'Blocked Event',
            'venue': 'Hall',
            'starts_at': timezone.now() + timedelta(days=30),
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_staff_can_create_and_patch_event(self):
        self.client.force_authenticate(self.staff)

        created = self.client.post('/api/v1/events/', {
            'name': 'Staff Event',
            'venue': 'Hall A',
            'starts_at': (timezone.now() + timedelta(days=30)).isoformat(),
            'status': Event.Status.DRAFT,
        }, format='json')
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)

        event_id = created.data['id']
        patched = self.client.patch(
            f'/api/v1/events/{event_id}/',
            {'status': Event.Status.PUBLISHED},
            format='json',
        )
        self.assertEqual(patched.status_code, status.HTTP_200_OK)
        self.assertEqual(patched.data['status'], Event.Status.PUBLISHED)

    def test_staff_can_create_ticket_type_for_event(self):
        self.client.force_authenticate(self.staff)

        response = self.client.post(
            f'/api/v1/events/{self.published.id}/ticket-types/',
            {'name': 'VIP', 'price': '75.00', 'capacity': 5},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['name'], 'VIP')
        self.assertNotIn('reserved_quantity', response.data)

    def test_public_ticket_type_detail_hides_inventory_counters(self):
        response = self.client.get(
            f'/api/v1/ticket-types/{self.ticket_type.id}/'
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertNotIn('reserved_quantity', response.data)
        self.assertNotIn('sold_quantity', response.data)

    def test_inventory_endpoint_is_staff_only(self):
        response = self.client.get(
            f'/api/v1/ticket-types/{self.ticket_type.id}/inventory/'
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

        self.client.force_authenticate(self.customer)
        response = self.client.get(
            f'/api/v1/ticket-types/{self.ticket_type.id}/inventory/'
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        self.client.force_authenticate(self.staff)
        response = self.client.get(
            f'/api/v1/ticket-types/{self.ticket_type.id}/inventory/'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['capacity'], 20)
