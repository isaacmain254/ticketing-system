from rest_framework import serializers

from .models import InventoryMovement, Reservation


class ReservationSerializer(serializers.ModelSerializer):
    total_price = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        read_only=True,
    )

    class Meta:
        model = Reservation
        fields = (
            'id',
            'ticket_type',
            'quantity',
            'unit_price',
            'total_price',
            'status',
            'expires_at',
            'confirmed_at',
            'created_at',
            'updated_at',
        )
        read_only_fields = fields


class CreateReservationSerializer(serializers.Serializer):
    ticket_type = serializers.UUIDField()
    quantity = serializers.IntegerField(min_value=1)


class InventoryMovementSerializer(serializers.ModelSerializer):
    class Meta:
        model = InventoryMovement
        fields = (
            'id',
            'ticket_type',
            'reservation',
            'movement_type',
            'quantity',
            'metadata',
            'created_at',
        )
        read_only_fields = fields
