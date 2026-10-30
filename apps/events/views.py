from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.accounts.permissions import IsStaffUser
from apps.reservations.models import InventoryMovement
from apps.reservations.serializers import InventoryMovementSerializer
from .models import Event, TicketType
from .serializers import (
    CreateTicketTypeSerializer,
    EventSerializer,
    TicketTypeInventorySerializer,
    TicketTypeSerializer,
)


class EventViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = EventSerializer

    def get_queryset(self):
        queryset = Event.objects.all()
        if self.action in ('list', 'retrieve'):
            return queryset.filter(status=Event.Status.PUBLISHED)
        return queryset

    def get_permissions(self):
        if self.action in ('create', 'update', 'partial_update'):
            return (IsStaffUser(),)
        return (AllowAny(),)

    @action(
        detail=True,
        methods=('post',),
        permission_classes=(IsStaffUser,),
        url_path='ticket-types',
    )
    def ticket_types(self, request, pk=None):
        event = self.get_object()
        serializer = CreateTicketTypeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ticket_type = TicketType.objects.create(
            event=event,
            **serializer.validated_data,
        )
        output = TicketTypeSerializer(
            ticket_type,
            context={'request': request},
        )
        return Response(output.data, status=status.HTTP_201_CREATED)


class TicketTypeViewSet(
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    queryset = TicketType.objects.select_related('event')
    serializer_class = TicketTypeSerializer

    def get_queryset(self):
        if self.action == 'inventory':
            return TicketType.objects.select_related('event')
        return TicketType.objects.select_related('event').filter(
            event__status=Event.Status.PUBLISHED
        )

    def get_permissions(self):
        if self.action == 'inventory':
            return (IsStaffUser(),)
        return (AllowAny(),)

    @action(detail=True, methods=('get',), permission_classes=(IsStaffUser,))
    def inventory(self, request, pk=None):
        ticket_type = self.get_object()
        serializer = TicketTypeInventorySerializer(
            ticket_type,
            context={'request': request},
        )
        return Response(serializer.data)


class InventoryMovementViewSet(
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    queryset = InventoryMovement.objects.select_related(
        'ticket_type',
        'reservation',
    )
    serializer_class = InventoryMovementSerializer
    permission_classes = (IsStaffUser,)
