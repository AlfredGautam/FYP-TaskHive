from unittest.mock import patch, MagicMock
from django.test import TestCase, RequestFactory, override_settings
from django.contrib.auth.models import User

from core.email_utils import _esc, _from_email, _site_url, _send_html_email
from core.rate_limit import rate_limit, _get_client_ip


# ---------------------------------------------------------------
# Email Utility Tests
# ---------------------------------------------------------------

class EscapeTests(TestCase):
    def test_escapes_html(self):
        self.assertEqual(_esc("<script>alert(1)</script>"), "&lt;script&gt;alert(1)&lt;/script&gt;")

    def test_empty_string(self):
        self.assertEqual(_esc(""), "")

    def test_none_returns_empty(self):
        self.assertEqual(_esc(None), "")

    def test_plain_string_unchanged(self):
        self.assertEqual(_esc("hello world"), "hello world")


class FromEmailTests(TestCase):
    @override_settings(DEFAULT_FROM_EMAIL="test@example.com")
    def test_returns_default_from_email(self):
        self.assertEqual(_from_email(), "test@example.com")

    @override_settings(DEFAULT_FROM_EMAIL=None, EMAIL_HOST_USER="host@example.com")
    def test_falls_back_to_host_user(self):
        self.assertEqual(_from_email(), "host@example.com")

    @override_settings(DEFAULT_FROM_EMAIL=None, EMAIL_HOST_USER=None)
    def test_falls_back_to_hardcoded(self):
        self.assertEqual(_from_email(), "taskhive65@gmail.com")


class SiteUrlTests(TestCase):
    @override_settings(SITE_URL="https://taskhive.com/")
    def test_strips_trailing_slash(self):
        self.assertEqual(_site_url(), "https://taskhive.com")

    @override_settings(SITE_URL="http://127.0.0.1:8000")
    def test_default_no_trailing(self):
        self.assertEqual(_site_url(), "http://127.0.0.1:8000")


class SendHtmlEmailTests(TestCase):
    @patch("core.email_utils.EmailMultiAlternatives")
    def test_send_success(self, MockEmail):
        instance = MockEmail.return_value
        instance.send.return_value = 1
        result = _send_html_email("Subj", "body", "<b>html</b>", ["a@b.com"])
        self.assertTrue(result)
        instance.attach_alternative.assert_called_once_with("<b>html</b>", "text/html")
        instance.send.assert_called_once_with(fail_silently=False)

    @patch("core.email_utils.EmailMultiAlternatives")
    @patch("core.email_utils.time.sleep")
    def test_send_retries_on_failure(self, mock_sleep, MockEmail):
        instance = MockEmail.return_value
        instance.send.side_effect = Exception("SMTP error")
        result = _send_html_email("Subj", "body", "<b>html</b>", ["a@b.com"])
        self.assertFalse(result)
        self.assertEqual(instance.send.call_count, 3)  # 1 initial + 2 retries


# ---------------------------------------------------------------
# Rate Limiting Tests
# ---------------------------------------------------------------

class RateLimitTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    @override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "test-rl"}})
    def test_allows_under_limit(self):
        @rate_limit(max_requests=3, window_seconds=60)
        def dummy_view(request):
            return MagicMock(status_code=200)

        request = self.factory.get("/")
        request.META["REMOTE_ADDR"] = "1.2.3.4"
        for _ in range(3):
            resp = dummy_view(request)
            self.assertEqual(resp.status_code, 200)

    @override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "test-rl2"}})
    def test_blocks_over_limit(self):
        @rate_limit(max_requests=2, window_seconds=60)
        def dummy_view(request):
            return MagicMock(status_code=200)

        request = self.factory.get("/")
        request.META["REMOTE_ADDR"] = "5.6.7.8"
        dummy_view(request)
        dummy_view(request)
        resp = dummy_view(request)
        self.assertEqual(resp.status_code, 429)


class GetClientIpTests(TestCase):
    def test_direct_ip(self):
        factory = RequestFactory()
        request = factory.get("/")
        request.META["REMOTE_ADDR"] = "10.0.0.1"
        self.assertEqual(_get_client_ip(request), "10.0.0.1")

    def test_xff_header(self):
        factory = RequestFactory()
        request = factory.get("/", HTTP_X_FORWARDED_FOR="203.0.113.50, 70.41.3.18")
        self.assertEqual(_get_client_ip(request), "203.0.113.50")


# ---------------------------------------------------------------
# Health Check Tests
# ---------------------------------------------------------------

class HealthCheckTests(TestCase):
    def test_health_endpoint_ok(self):
        response = self.client.get("/api/health/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["database"], "connected")


# ---------------------------------------------------------------
# Model Tests
# ---------------------------------------------------------------

class TeamMembershipTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="test@test.com", password="pass123")

    def test_profile_auto_created(self):
        self.assertTrue(hasattr(self.user, "profile"))
        self.assertEqual(self.user.profile.display_name, self.user.username)

    def test_team_creation(self):
        from core.models import Team, TeamMembership
        team = Team.objects.create(name="Test Team", code="TEST01", created_by=self.user)
        membership = TeamMembership.objects.create(team=team, user=self.user, role="head")
        self.assertEqual(membership.role, "head")
        self.assertEqual(team.memberships.count(), 1)
