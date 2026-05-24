"""
Unit tests for authentication APIs:
  - Login
  - Registration (sends OTP)
  - Registration verification
  - Logout
  - Password reset flow
"""
import json
from unittest.mock import patch, MagicMock

from django.test import TestCase, Client, override_settings
from django.contrib.auth.models import User


LOCMEM_CACHE = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "test-auth"}}


@override_settings(CACHES=LOCMEM_CACHE)
class LoginAPITests(TestCase):
    def setUp(self):
        self.client = Client(enforce_csrf_checks=False)
        self.user = User.objects.create_user(
            username="alice@example.com",
            email="alice@example.com",
            password="Secret123!",
            first_name="Alice",
        )

    def _post_json(self, url, payload):
        return self.client.post(url, json.dumps(payload), content_type="application/json")

    def test_login_success(self):
        resp = self._post_json("/api/login/", {"email": "alice@example.com", "password": "Secret123!"})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["ok"])

    def test_login_wrong_password(self):
        resp = self._post_json("/api/login/", {"email": "alice@example.com", "password": "wrong"})
        data = resp.json()
        self.assertFalse(data["ok"])

    def test_login_nonexistent_user(self):
        resp = self._post_json("/api/login/", {"email": "noone@example.com", "password": "whatever"})
        data = resp.json()
        self.assertFalse(data["ok"])

    def test_login_get_not_allowed(self):
        resp = self.client.get("/api/login/")
        self.assertEqual(resp.status_code, 405)

    def test_login_invalid_json(self):
        resp = self.client.post("/api/login/", "not json", content_type="application/json")
        self.assertEqual(resp.status_code, 400)

    def test_login_missing_fields(self):
        resp = self._post_json("/api/login/", {"email": "alice@example.com"})
        data = resp.json()
        self.assertFalse(data["ok"])


@override_settings(CACHES=LOCMEM_CACHE)
class RegisterAPITests(TestCase):
    def setUp(self):
        self.client = Client(enforce_csrf_checks=False)

    def _post_json(self, url, payload):
        return self.client.post(url, json.dumps(payload), content_type="application/json")

    @patch("core.views.auth._send_email_verification_code")
    def test_register_sends_otp(self, mock_send):
        mock_send.return_value = None
        resp = self._post_json("/api/register/", {
            "name": "Bob",
            "email": "bob@example.com",
            "password": "Pass1234!",
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["ok"])
        mock_send.assert_called_once()

    def test_register_missing_fields(self):
        resp = self._post_json("/api/register/", {"email": "bob@example.com"})
        data = resp.json()
        self.assertFalse(data["ok"])

    def test_register_duplicate_email(self):
        User.objects.create_user(username="existing@example.com", email="existing@example.com", password="pass")
        resp = self._post_json("/api/register/", {
            "name": "Dup",
            "email": "existing@example.com",
            "password": "Pass1234!",
        })
        data = resp.json()
        self.assertFalse(data["ok"])

    def test_register_get_not_allowed(self):
        resp = self.client.get("/api/register/")
        self.assertEqual(resp.status_code, 405)


@override_settings(CACHES=LOCMEM_CACHE)
class LogoutAPITests(TestCase):
    def setUp(self):
        self.client = Client(enforce_csrf_checks=False)
        self.user = User.objects.create_user(
            username="alice@example.com",
            email="alice@example.com",
            password="Secret123!",
        )

    def test_logout_when_logged_in(self):
        self.client.login(username="alice@example.com", password="Secret123!")
        resp = self.client.post("/api/logout/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["ok"])

    def test_logout_when_not_logged_in(self):
        resp = self.client.post("/api/logout/")
        self.assertEqual(resp.status_code, 200)


@override_settings(CACHES=LOCMEM_CACHE)
class MeAPITests(TestCase):
    def setUp(self):
        self.client = Client(enforce_csrf_checks=False)
        self.user = User.objects.create_user(
            username="alice@example.com",
            email="alice@example.com",
            password="Secret123!",
            first_name="Alice",
        )

    def test_me_authenticated(self):
        self.client.login(username="alice@example.com", password="Secret123!")
        resp = self.client.get("/api/me/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["user"]["email"], "alice@example.com")

    def test_me_unauthenticated(self):
        resp = self.client.get("/api/me/")
        # @login_required redirects to login page
        self.assertEqual(resp.status_code, 302)
