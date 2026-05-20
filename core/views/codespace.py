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
from core.file_validation import validate_code_file

logger = logging.getLogger(__name__)


@login_required
def api_code_list(request):
    files = CodeFile.objects.filter(owner=request.user).order_by("-updated_at")
    return JsonResponse({
        "ok": True,
        "files": [
            {
                "id": f.id,
                "filename": f.filename,
                "updated_at": f.updated_at.isoformat() if f.updated_at else None,
            }
            for f in files
        ]
    })


@login_required
def api_code_get(request, file_id):
    try:
        f = CodeFile.objects.get(id=file_id, owner=request.user)
    except CodeFile.DoesNotExist:
        return JsonResponse({"ok": False, "error": "File not found"}, status=404)

    return JsonResponse({
        "ok": True,
        "file": {
            "id": f.id,
            "filename": f.filename,
            "content": f.content or ""
        }
    })


@require_POST
@login_required
def api_code_delete(request):
    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"ok": False, "error": "Invalid JSON"}, status=400)

    file_id = data.get("file_id")
    if not file_id:
        return JsonResponse({"ok": False, "error": "file_id required"}, status=400)

    try:
        f = CodeFile.objects.get(id=file_id, owner=request.user)
    except CodeFile.DoesNotExist:
        return JsonResponse({"ok": False, "error": "File not found"}, status=404)

    f.delete()
    return JsonResponse({"ok": True})


@require_POST
@login_required
def api_code_upload(request):
    up = request.FILES.get("file")
    if not up:
        return JsonResponse({"ok": False, "error": "No file uploaded"}, status=400)

    err = validate_code_file(up)
    if err:
        return JsonResponse({"ok": False, "error": err}, status=400)

    try:
        text = up.read().decode("utf-8", errors="ignore")
    except Exception:
        text = ""

    f = CodeFile.objects.create(
        owner=request.user,
        filename=up.name,
        content=text
    )

    return JsonResponse({"ok": True, "file_id": f.id, "filename": f.filename})


@require_POST
@login_required
def api_code_save(request):
    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"ok": False, "error": "Invalid JSON"}, status=400)

    file_id = data.get("file_id")
    content = data.get("content", "")

    if not file_id:
        return JsonResponse({"ok": False, "error": "file_id required"}, status=400)

    try:
        f = CodeFile.objects.get(id=file_id, owner=request.user)
    except CodeFile.DoesNotExist:
        return JsonResponse({"ok": False, "error": "File not found"}, status=404)

    f.content = content
    f.updated_at = timezone.now()
    f.save(update_fields=["content", "updated_at"])

    return JsonResponse({"ok": True})


@require_POST
@login_required
def api_code_create(request):
    """
    Create an empty/new file in DB
    Expected JSON: { "filename": "app.js", "content": "" }
    """
    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"ok": False, "error": "Invalid JSON"}, status=400)

    filename = (data.get("filename") or "").strip()
    content = data.get("content") or ""

    if not filename:
        return JsonResponse({"ok": False, "error": "filename required"}, status=400)

    # optional: avoid duplicates per user
    existing = CodeFile.objects.filter(owner=request.user, filename=filename).first()
    if existing:
        return JsonResponse({"ok": True, "file_id": existing.id, "filename": existing.filename, "exists": True})

    f = CodeFile.objects.create(
        owner=request.user,
        filename=filename,
        content=content
    )

    return JsonResponse({"ok": True, "file_id": f.id, "filename": f.filename, "exists": False})


