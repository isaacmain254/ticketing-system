from rest_framework import serializers

from .models import Event, TicketType


class EventSerializer(serializers.ModelSerializer):
    class Meta:
        model = Event
        fields = (
            'id',
            'name',
            'description',
            'venue',
            'starts_at',
            'status',
            'created_at',
            'updated_at',
        )
        read_only_fields = ('id', 'created_at', 'updated_at')


class TicketTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = TicketType
        fields = (
            'id',
            'event',
            'name',
            'price',
            'created_at',
            'updated_at',
        )
        read_only_fields = (
            'id',
            'event',
            'created_at',
            'updated_at',
        )


class TicketTypeInventorySerializer(serializers.ModelSerializer):
    availability = serializers.IntegerField(read_only=True)

    class Meta:
        model = TicketType
        fields = (
            'id',
            'capacity',
            'reserved_quantity',
            'sold_quantity',
            'availability',
        )
        read_only_fields = fields


class CreateTicketTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = TicketType
        fields = ('id', 'name', 'price', 'capacity')
        read_only_fields = ('id',)
