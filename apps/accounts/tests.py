from django.contrib.auth import get_user_model
from django.urls import reverse
from types import SimpleNamespace
from rest_framework import status
from rest_framework.test import APITestCase

from .permissions import IsStaffUser


class AccountAPITests(APITestCase):
    def test_schema_and_interactive_documentation_routes(self):
        for path in ('/api/schema/', '/api/docs/', '/api/redoc/'):
            response = self.client.get(path)
            self.assertEqual(response.status_code, status.HTTP_200_OK)

        schema = self.client.get('/api/schema/', {'format': 'json'})
        self.assertEqual(schema.status_code, status.HTTP_200_OK)
        body = schema.json()
        self.assertIn('/api/v1/reservations/', body['paths'])
        self.assertIn('bearerAuth', body['components']['securitySchemes'])

    def test_registration_always_creates_customer(self):
        response = self.client.post(
            '/api/auth/register/',
            {
                'username': 'newcustomer',
                'email': 'customer@example.com',
                'password': 'C0mpl3x!Passphrase',
                'password_confirm': 'C0mpl3x!Passphrase',
                'role': 'STAFF',
                'is_staff': True,
                'is_superuser': True,
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        user = get_user_model().objects.get(username='newcustomer')
        self.assertEqual(user.role, get_user_model().Role.CUSTOMER)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)

    def test_registration_password_confirmation_is_required(self):
        response = self.client.post(
            '/api/auth/register/',
            {
                'username': 'mismatch',
                'password': 'C0mpl3x!Passphrase',
                'password_confirm': 'DifferentPassphrase!42',
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_jwt_obtain_and_refresh(self):
        user = get_user_model().objects.create_user(
            username='jwtuser',
            password='C0mpl3x!Passphrase',
        )

        obtain = self.client.post(
            '/api/auth/token/',
            {'username': user.username, 'password': 'C0mpl3x!Passphrase'},
            format='json',
        )
        self.assertEqual(obtain.status_code, status.HTTP_200_OK)
        self.assertIn('access', obtain.data)
        self.assertIn('refresh', obtain.data)

        refresh = self.client.post(
            '/api/auth/token/refresh/',
            {'refresh': obtain.data['refresh']},
            format='json',
        )
        self.assertEqual(refresh.status_code, status.HTTP_200_OK)
        self.assertIn('access', refresh.data)

    def test_versioned_auth_routes(self):
        response = self.client.post(
            '/api/v1/auth/register/',
            {
                'username': 'versioned-user',
                'password': 'C0mpl3x!Passphrase',
                'password_confirm': 'C0mpl3x!Passphrase',
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        obtain = self.client.post(
            '/api/v1/auth/token/',
            {
                'username': 'versioned-user',
                'password': 'C0mpl3x!Passphrase',
            },
            format='json',
        )
        self.assertEqual(obtain.status_code, status.HTTP_200_OK)
        self.assertIn('access', obtain.data)

        refresh = self.client.post(
            '/api/v1/auth/token/refresh/',
            {'refresh': obtain.data['refresh']},
            format='json',
        )
        self.assertEqual(refresh.status_code, status.HTTP_200_OK)
        self.assertIn('access', refresh.data)

    def test_is_staff_user_permission(self):
        permission = IsStaffUser()
        staff = get_user_model()(
            username='staff',
            role=get_user_model().Role.STAFF,
        )
        customer = get_user_model()(
            username='customer',
            role=get_user_model().Role.CUSTOMER,
        )

        self.assertTrue(permission.has_permission(SimpleNamespace(user=staff), None))
        self.assertFalse(permission.has_permission(SimpleNamespace(user=customer), None))
