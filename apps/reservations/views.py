from rest_framework import viewsets

from .models import Reservation
from .permissions import IsReservationOwner
from .serializers import ReservationSerializer


class ReservationViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ReservationSerializer
    permission_classes = (IsReservationOwner,)

    def get_queryset(self):
        queryset = Reservation.objects.select_related(
            'customer',
            'ticket_type',
            'ticket_type__event',
        )
        user = self.request.user
        if getattr(user, 'role', None) == 'STAFF':
            return queryset
        return queryset.filter(customer=user)
