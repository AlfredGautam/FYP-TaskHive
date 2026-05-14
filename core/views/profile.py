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


@login_required
@require_POST
@rate_limit(max_requests=10, window_seconds=60)
def api_profile_change_password(request):
    """Allow an authenticated user to change their own password.
    Requires the current password for verification."""
    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"ok": False, "error": "Invalid JSON"}, status=400)

    current_password = data.get("current_password") or ""
    new_password = data.get("new_password") or ""
    confirm_password = data.get("confirm_password") or ""

    if not current_password or not new_password or not confirm_password:
        return JsonResponse({"ok": False, "error": "All fields are required."}, status=400)

    if new_password != confirm_password:
        return JsonResponse({"ok": False, "error": "New passwords do not match."}, status=400)

    if len(new_password) < 6:
        return JsonResponse({"ok": False, "error": "New password must be at least 6 characters."}, status=400)

    if new_password == current_password:
        return JsonResponse({"ok": False, "error": "New password must be different from your current password."}, status=400)

    user = request.user
    if not user.check_password(current_password):
        return JsonResponse({"ok": False, "error": "Current password is incorrect."}, status=400)

    try:
        user.set_password(new_password)
        user.save()
        # Keep the user logged in after password change
        from django.contrib.auth import update_session_auth_hash
        update_session_auth_hash(request, user)
    except Exception as e:
        return JsonResponse({"ok": False, "error": f"Password update failed: {str(e)}"}, status=500)

    return JsonResponse({"ok": True, "message": "Password changed successfully."})


@login_required
@require_POST
def api_profile_update(request):
    profile, _ = UserProfile.objects.get_or_create(user=request.user)

    payload = request.POST if request.POST else {}
    if request.content_type and "application/json" in request.content_type:
        try:
            payload = json.loads(request.body.decode("utf-8"))
        except Exception:
            payload = {}

    profile.display_name = payload.get("displayName", payload.get("display_name", profile.display_name))
    profile.username_public = payload.get("username", payload.get("username_public", profile.username_public))
    profile.tagline = payload.get("tagline", profile.tagline)
    profile.bio = payload.get("bio", profile.bio)
    profile.github = payload.get("github", profile.github)
    profile.linkedin = payload.get("linkedin", profile.linkedin)
    profile.theme_mode = payload.get("themeMode", payload.get("theme_mode", profile.theme_mode))
    profile.accent_color = payload.get("accentColor", payload.get("accent_color", profile.accent_color))

    if request.FILES.get("photo"):
        profile.photo = request.FILES["photo"]
    if request.FILES.get("cover"):
        profile.cover_photo = request.FILES["cover"]

    profile.save()

    request.user.first_name = payload.get("name", request.user.first_name)
    request.user.email = payload.get("email", request.user.email)
    request.user.save()

    return JsonResponse({"ok": True})


@login_required
def api_profile_get(request):
    profile, _ = UserProfile.objects.get_or_create(user=request.user)

    return JsonResponse({
        "ok": True,
        "profile": {
            "display_name": profile.display_name,
            "username_public": profile.username_public,
            "tagline": profile.tagline,
            "bio": profile.bio,
            "github": profile.github,
            "linkedin": profile.linkedin,
            "theme_mode": profile.theme_mode,
            "accent_color": profile.accent_color,
            "photo_url": profile.photo.url if profile.photo else "",
            "cover_url": profile.cover_photo.url if profile.cover_photo else "",
            "email": request.user.email,
            "name": request.user.get_full_name() or request.user.username,
        }
    })


@login_required
def api_profile(request):
    return api_profile_get(request)


@login_required
@require_POST
def api_profile_save(request):
    return api_profile_update(request)


@login_required
@require_POST
def api_profile_photo(request):
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    photo = request.FILES.get("photo")
    if not photo:
        return JsonResponse({"ok": False, "error": "photo file required"}, status=400)
    profile.photo = photo
    profile.save(update_fields=["photo", "updated_at"])
    return JsonResponse({"ok": True, "photo_url": profile.photo.url if profile.photo else ""})


@login_required
@require_POST
def api_profile_cover(request):
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    cover = request.FILES.get("cover")
    if not cover:
        return JsonResponse({"ok": False, "error": "cover file required"}, status=400)
    profile.cover_photo = cover
    profile.save(update_fields=["cover_photo", "updated_at"])
    return JsonResponse({"ok": True, "cover_url": profile.cover_photo.url if profile.cover_photo else ""})


@login_required
@require_POST
def api_profile_delete_account(request):
    user = request.user
    logout(request)
    user.delete()
    return JsonResponse({"ok": True, "redirect": "/login/"})


@login_required
def api_profile_public(request, username: str):
    target_user = User.objects.filter(username=username).first()
    if not target_user:
        return JsonResponse({"ok": False, "error": "User not found"}, status=404)

    profile, _ = UserProfile.objects.get_or_create(user=target_user)

    # Team info
    from core.models import TeamMembership, Task
    memberships = TeamMembership.objects.filter(user=target_user).select_related("team")
    teams = [{"name": m.team.name, "role": m.get_role_display()} for m in memberships]

    # Task stats
    task_count = Task.objects.filter(assignees=target_user).count()
    tasks_done = Task.objects.filter(assignees=target_user, column__name__icontains="done").count()

    return JsonResponse({
        "ok": True,
        "profile": {
            "display_name": profile.display_name,
            "username_public": profile.username_public,
            "tagline": profile.tagline,
            "bio": profile.bio,
            "github": profile.github,
            "linkedin": profile.linkedin,
            "photo_url": profile.photo.url if profile.photo else "",
            "cover_url": profile.cover_photo.url if profile.cover_photo else "",
            "name": target_user.get_full_name() or target_user.username,
            "email": target_user.email,
            "joined": target_user.date_joined.strftime("%b %Y"),
            "teams": teams,
            "task_count": task_count,
            "tasks_done": tasks_done,
        },
    })


