from decimal import Decimal
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

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
