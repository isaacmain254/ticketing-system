from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import EventViewSet, InventoryMovementViewSet, TicketTypeViewSet


router = DefaultRouter()
router.register('events', EventViewSet, basename='event')
router.register('ticket-types', TicketTypeViewSet, basename='ticket-type')
router.register(
    'inventory-movements',
    InventoryMovementViewSet,
    basename='inventory-movement',
)

urlpatterns = router.urls
