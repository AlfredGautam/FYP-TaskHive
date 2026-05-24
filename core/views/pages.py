"""Auto-split from the original core/views.py.

If you add a new view here, also re-export it from core/views/__init__.py
(or add `from .<this_module> import *`).
"""
import json
import logging
import random
import re
import secrets
from datetime import timedelta, date

from google.oauth2 import id_token as google_id_token
from google.auth.transport import requests as google_requests

from django.conf import settings
from django.core.mail import send_mail
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.hashers import make_password, check_password
from django.contrib.auth.models import User
from django.http import JsonResponse, HttpResponse
from django.shortcuts import render, redirect
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie, csrf_exempt
from django.views.decorators.http import require_POST

from core.models import (
    CodeFile, PasswordOTP, EmailVerificationOTP, UserProfile,
    Team, TeamMembership, TeamInvitation,
    Workspace, Board, Column, Task, Project, ProjectFile,
    ApprovalRequest, Notification, ActivityLog,
    Subtask, TaskAttachment, TaskComment,
)
from core.email_utils import (
    send_welcome_email, send_task_assigned_email,
    send_deadline_reminder_email, send_team_invitation_email,
)
from core.rate_limit import rate_limit

logger = logging.getLogger(__name__)


def error_404(request, exception=None):
    return render(request, "core/404.html", status=404)


def error_500(request):
    return render(request, "core/500.html", status=500)


def api_health(request):
    """Health check endpoint for monitoring."""
    from django.db import connection
    try:
        connection.ensure_connection()
        db_ok = True
    except Exception:
        db_ok = False
    status = 200 if db_ok else 503
    return JsonResponse({
        "status": "ok" if db_ok else "degraded",
        "database": "connected" if db_ok else "unavailable",
    }, status=status)


def dashboard_page(request):
    return render(request, "core/dashboard.html")


@ensure_csrf_cookie
def login_page(request):
    # If an admin is here, log them out so they can use the normal login
    if request.user.is_authenticated and (request.user.is_staff or request.user.is_superuser):
        logout(request)
    return render(request, "core/login_new.html", {
        "google_client_id": settings.GOOGLE_CLIENT_ID,
    })


@login_required
def user_page(request):
    if request.user.is_staff or request.user.is_superuser:
        return redirect("/admin/")
    return render(request, "core/user.html")


@login_required
def workspace(request):
    if request.user.is_staff or request.user.is_superuser:
        return redirect("/admin/")
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if not profile.current_team_id:
        return render(request, "core/user.html")
    return render(request, "core/index.html")


@login_required
def workspace_team(request, team_id: int):
    if request.user.is_staff or request.user.is_superuser:
        return redirect("/admin/")
    is_member = TeamMembership.objects.filter(team_id=team_id, user=request.user).exists()
    if not is_member:
        return render(request, "core/user.html")

    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if profile.current_team_id != team_id:
        profile.current_team_id = team_id
        profile.save(update_fields=["current_team"])

    return render(request, "core/index.html")


@login_required
def analytics_page(request):
    if request.user.is_staff or request.user.is_superuser:
        return redirect("/admin/")
    return render(request, "core/analytics.html")


@ensure_csrf_cookie
@login_required
def codespace_page(request):
    if request.user.is_staff or request.user.is_superuser:
        return redirect("/admin/")
    return render(request, "core/codespace.html")


@ensure_csrf_cookie
@login_required
def profile_page(request):
    if request.user.is_staff or request.user.is_superuser:
        return redirect("/admin/")
    return render(request, "core/profile.html")


@login_required
def public_profile_page(request, username: str):
    return render(request, "core/public_profile.html", {"profile_username": username})


