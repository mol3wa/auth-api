from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status
from unittest.mock import patch
from django.contrib.auth import get_user_model
from .models import EmailOTP

User = get_user_model()

class AuthAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.signup_url = reverse('signup')
        self.verify_email_url = reverse('verify-email')
        self.login_url = reverse('login')
        self.update_email_url = reverse('initiate-email-update')
        self.verify_update_url = reverse('verify-email-update')
        self.delete_url = reverse('delete-account')
        self.user_data = {
            'email': 'test@example.com',
            'first_name': 'John',
            'last_name': 'Doe',
            'password': 'strongPass123'
        }

    def _mock_send_otp(self):
        return patch('accounts.views.send_otp_email')

    # ---------- Signup ----------
    def test_signup_success(self):
        with self._mock_send_otp() as mock_send:
            response = self.client.post(self.signup_url, self.user_data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn('Signup successful', response.data['detail'])
        user = User.objects.get(email=self.user_data['email'])
        self.assertFalse(user.is_active)
        self.assertTrue(EmailOTP.objects.filter(user=user, purpose='signup').exists())

    def test_signup_duplicate_email(self):
        User.objects.create_user(**self.user_data)
        with self._mock_send_otp():
            response = self.client.post(self.signup_url, self.user_data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    # ---------- Verify Email ----------
    def test_verify_email_success(self):
        user = User.objects.create_user(**self.user_data, is_active=False)
        otp = EmailOTP.generate_otp(user, 'signup')
        response = self.client.post(self.verify_email_url, {
            'email': user.email,
            'otp': otp.otp_code
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        user.refresh_from_db()
        self.assertTrue(user.is_active)
        self.assertTrue(user.is_email_verified)
        otp.refresh_from_db()
        self.assertTrue(otp.is_verified)

    def test_verify_email_invalid_otp(self):
        user = User.objects.create_user(**self.user_data, is_active=False)
        EmailOTP.generate_otp(user, 'signup')
        response = self.client.post(self.verify_email_url, {
            'email': user.email,
            'otp': '000000'
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    # ---------- Login ----------
    def test_login_success(self):
        user = User.objects.create_user(**self.user_data, is_active=True, is_email_verified=True)
        response = self.client.post(self.login_url, {
            'email': self.user_data['email'],
            'password': self.user_data['password']
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('access', response.data)

    def test_login_inactive_user(self):
        user = User.objects.create_user(**self.user_data, is_active=False)
        response = self.client.post(self.login_url, {
            'email': self.user_data['email'],
            'password': self.user_data['password']
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    # ---------- Email Update ----------
    def _authenticate(self):
        user = User.objects.create_user(**self.user_data, is_active=True, is_email_verified=True)
        token_response = self.client.post(self.login_url, {
            'email': self.user_data['email'],
            'password': self.user_data['password']
        }, format='json')
        token = token_response.data['access']
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
        return user

    def test_initiate_email_update(self):
        user = self._authenticate()
        with self._mock_send_otp() as mock_send:
            response = self.client.post(self.update_email_url, {
                'new_email': 'new@example.com'
            }, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        otp = EmailOTP.objects.get(user=user, purpose='email_update')
        self.assertEqual(otp.new_email, 'new@example.com')
        mock_send.assert_called_once()

    def test_verify_email_update(self):
        user = self._authenticate()
        new_email = 'new@example.com'
        otp = EmailOTP.generate_otp(user, 'email_update', new_email=new_email)
        response = self.client.post(self.verify_update_url, {
            'otp': otp.otp_code
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        user.refresh_from_db()
        self.assertEqual(user.email, new_email)

    # ---------- Delete Account ----------
    def test_delete_account_success(self):
        user = self._authenticate()
        response = self.client.delete(self.delete_url, {
            'password': self.user_data['password']
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(User.objects.filter(id=user.id).exists())

    def test_delete_account_wrong_password(self):
        self._authenticate()
        response = self.client.delete(self.delete_url, {
            'password': 'wrongpass'
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue(User.objects.filter(email=self.user_data['email']).exists())