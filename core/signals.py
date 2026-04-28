"""
Signal handlers for tracking login history and failed login attempts.
"""
from django.contrib.auth.signals import user_logged_in, user_login_failed
from django.dispatch import receiver


def _get_client_ip(request):
    """Extract real client IP from request, respecting X-Forwarded-For."""
    if request is None:
        return None
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def _get_user_agent(request):
    if request is None:
        return ""
    return request.META.get("HTTP_USER_AGENT", "")[:500]


@receiver(user_logged_in)
def on_user_logged_in(sender, request, user, **kwargs):
    from .models import LoginHistory
    LoginHistory.objects.create(
        user=user,
        ip_address=_get_client_ip(request),
        user_agent=_get_user_agent(request),
    )


@receiver(user_login_failed)
def on_user_login_failed(sender, credentials, request, **kwargs):
    from .models import FailedLoginAttempt
    FailedLoginAttempt.objects.create(
        username_attempted=credentials.get("username", "")[:150],
        ip_address=_get_client_ip(request),
        user_agent=_get_user_agent(request),
    )
