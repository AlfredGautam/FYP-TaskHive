"""
Signal handlers for tracking login history, failed login attempts,
and broadcasting admin dashboard refresh events via WebSocket.
"""
from django.contrib.auth.signals import user_logged_in, user_login_failed
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync


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


def _notify_admin_dashboard(reason="data_changed"):
    """Broadcast a refresh event to all connected admin dashboard WebSockets
    and invalidate the cached dashboard stats."""
    try:
        from django.core.cache import cache
        cache.delete("admin_dashboard_stats")
    except Exception:
        pass
    try:
        layer = get_channel_layer()
        async_to_sync(layer.group_send)(
            "admin_dashboard",
            {"type": "admin_refresh", "reason": reason},
        )
    except Exception:
        pass


@receiver(user_logged_in)
def on_user_logged_in(sender, request, user, **kwargs):
    from .models import LoginHistory
    LoginHistory.objects.create(
        user=user,
        ip_address=_get_client_ip(request),
        user_agent=_get_user_agent(request),
    )
    _notify_admin_dashboard("user_login")


@receiver(user_login_failed)
def on_user_login_failed(sender, credentials, request, **kwargs):
    from .models import FailedLoginAttempt
    FailedLoginAttempt.objects.create(
        username_attempted=credentials.get("username", "")[:150],
        ip_address=_get_client_ip(request),
        user_agent=_get_user_agent(request),
    )
    _notify_admin_dashboard("failed_login")


# Broadcast when users are created/updated
@receiver(post_save, sender="auth.User")
def on_user_saved(sender, instance, created, **kwargs):
    _notify_admin_dashboard("user_created" if created else "user_updated")


# Broadcast when key models change
def _connect_model_signals():
    from .models import Task, Team, TeamMembership, Project, Workspace

    for model, label in [
        (Task, "task"),
        (Team, "team"),
        (TeamMembership, "membership"),
        (Project, "project"),
        (Workspace, "workspace"),
    ]:
        def _make_save_handler(lbl):
            def handler(sender, instance, created, **kwargs):
                _notify_admin_dashboard(f"{lbl}_{'created' if created else 'updated'}")
            return handler

        def _make_delete_handler(lbl):
            def handler(sender, instance, **kwargs):
                _notify_admin_dashboard(f"{lbl}_deleted")
            return handler

        post_save.connect(_make_save_handler(label), sender=model, weak=False)
        post_delete.connect(_make_delete_handler(label), sender=model, weak=False)


_connect_model_signals()
