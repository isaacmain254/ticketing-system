from rest_framework.permissions import BasePermission


class IsStaffUser(BasePermission):
    message = 'Staff access required.'

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and getattr(request.user, 'role', None) == 'STAFF'
        )
