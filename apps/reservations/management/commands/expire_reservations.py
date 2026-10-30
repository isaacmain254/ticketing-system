from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.reservations.models import Reservation
from apps.reservations.services import expire_reservation


class Command(BaseCommand):
    help = 'Expire pending reservations whose deadlines have passed.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--batch-size',
            type=int,
            default=100,
            help='Maximum number of reservations to process (default: 100).',
        )

    def handle(self, *args, **options):
        batch_size = options['batch_size']
        if batch_size <= 0:
            raise CommandError('--batch-size must be a positive integer.')

        now = timezone.now()
        reservation_ids = list(
            Reservation.objects.filter(
                status=Reservation.Status.PENDING,
                expires_at__lte=now,
            )
            .order_by('expires_at', 'id')
            .values_list('id', flat=True)[:batch_size]
        )

        expired_count = 0
        for reservation_id in reservation_ids:
            if expire_reservation(reservation_id, now=now):
                expired_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f'Expired {expired_count} reservation(s).'
            )
        )
