from rest_framework import generics, permissions, status
from rest_framework.response import Response
from drf_spectacular.utils import OpenApiExample, extend_schema

from .serializers import RegisterSerializer, UserSerializer


class RegisterView(generics.CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = (permissions.AllowAny,)

    def get_serializer_class(self):
        return RegisterSerializer

    @extend_schema(
        summary='Register a customer',
        request=RegisterSerializer,
        responses={201: UserSerializer},
        examples=[
            OpenApiExample(
                'Registration example',
                value={
                    'username': 'example_customer',
                    'email': 'customer@example.com',
                    'password': 'ExamplePassphrase!42',
                    'password_confirm': 'ExamplePassphrase!42',
                },
                request_only=True,
            )
        ],
    )
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        response_serializer = UserSerializer(user)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)
