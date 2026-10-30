from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend

from .backends import StableOrderingFilter
from .filters import ReservationFilterSet

from .exceptions import (
    InsufficientInventory,
    InvalidReservationQuantity,
    InvalidReservationTransition,
    ReservationNotFound,
    ReservationOwnershipDenied,
    TicketTypeNotAvailable,
)
from .models import Reservation
from .permissions import IsReservationOwner
from .serializers import (
    CreateReservationSerializer,
    InventoryMovementSerializer,
    ReservationSerializer,
)
from .services import cancel_reservation, confirm_reservation, create_reservation


class ReservationViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = ReservationSerializer
    permission_classes = (IsReservationOwner,)
    filter_backends = (DjangoFilterBackend, StableOrderingFilter)
    filterset_class = ReservationFilterSet
    ordering_fields = ('created_at', 'expires_at', 'status')

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

    def get_serializer_class(self):
        if self.action == 'create':
            return CreateReservationSerializer
        return ReservationSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            reservation = create_reservation(
                customer=request.user,
                ticket_type_id=serializer.validated_data['ticket_type'],
                quantity=serializer.validated_data['quantity'],
            )
        except InvalidReservationQuantity as exc:
            raise ValidationError({'quantity': str(exc)})
        except TicketTypeNotAvailable as exc:
            raise NotFound(str(exc))
        except InsufficientInventory as exc:
            return Response(
                {'detail': str(exc)},
                status=status.HTTP_409_CONFLICT,
            )

        output = ReservationSerializer(
            reservation,
            context={'request': request},
        )
        return Response(output.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=('post',), permission_classes=(IsReservationOwner,))
    def confirm(self, request, pk=None):
        try:
            reservation = confirm_reservation(
                customer=request.user,
                reservation_id=pk,
            )
        except ReservationOwnershipDenied:
            raise NotFound('Reservation not found.')
        except ReservationNotFound as exc:
            raise NotFound(str(exc))
        except InvalidReservationTransition as exc:
            return Response(
                {'detail': str(exc)},
                status=status.HTTP_409_CONFLICT,
            )

        output = ReservationSerializer(
            reservation,
            context={'request': request},
        )
        if reservation.status == Reservation.Status.EXPIRED:
            return Response(
                output.data,
                status=status.HTTP_409_CONFLICT,
            )
        return Response(output.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=('post',), permission_classes=(IsReservationOwner,))
    def cancel(self, request, pk=None):
        try:
            reservation = cancel_reservation(
                customer=request.user,
                reservation_id=pk,
            )
        except ReservationOwnershipDenied:
            raise NotFound('Reservation not found.')
        except ReservationNotFound as exc:
            raise NotFound(str(exc))
        except InvalidReservationTransition as exc:
            return Response(
                {'detail': str(exc)},
                status=status.HTTP_409_CONFLICT,
            )

        output = ReservationSerializer(
            reservation,
            context={'request': request},
        )
        return Response(output.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=('get',), permission_classes=(IsReservationOwner,))
    def movements(self, request, pk=None):
        reservation = self.get_object()
        queryset = reservation.inventory_movements.select_related(
            'ticket_type',
        ).order_by('created_at', 'id')
        page = self.paginate_queryset(queryset)
        serializer = InventoryMovementSerializer(
            page if page is not None else queryset,
            many=True,
            context={'request': request},
        )
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)
