from rest_framework.permissions import BasePermission


class IsReservationOwner(BasePermission):
    message = 'You can only access your own reservations.'

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj):
        user = request.user
        if getattr(user, 'role', None) == 'STAFF':
            return True
        return obj.customer_id == user.id
