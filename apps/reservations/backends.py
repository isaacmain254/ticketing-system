from rest_framework.exceptions import ValidationError
from rest_framework.filters import OrderingFilter


class StableOrderingFilter(OrderingFilter):
    allowed_fields = (
        'created_at',
        'expires_at',
        'status',
    )
    ordering_param = 'ordering'

    def get_ordering(self, request, queryset, view):
        value = request.query_params.get(self.ordering_param)
        if not value:
            return None

        fields = [field.strip() for field in value.split(',') if field.strip()]
        allowed = set(getattr(view, 'ordering_fields', self.allowed_fields))
        invalid = []
        result = []
        for field in fields:
            name = field[1:] if field.startswith('-') else field
            if name not in allowed:
                invalid.append(field)
            else:
                result.append(field)
        if invalid:
            raise ValidationError({
                'ordering': (
                    f"Invalid ordering field(s): {', '.join(invalid)}. "
                    "Allowed fields: created_at, expires_at, status."
                )
            })

        if result and 'id' not in result and '-id' not in result:
            result.append('-id')
        return result
