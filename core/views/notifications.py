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
from core.views.workspace_api import (
    _get_user_team, _serialize_notification, _notify_team, _log_activity,
)

logger = logging.getLogger(__name__)


@login_required
def api_notifications_list(request):
    from django.db.models import Q
    from django.utils import timezone
    from datetime import timedelta

    seven_days_ago = timezone.now() - timedelta(days=7)

    # Auto-delete notifications older than 7 days for this recipient
    Notification.objects.filter(recipient=request.user, created_at__lt=seven_days_ago).delete()

    team, membership = _get_user_team(request.user)

    # Team notifications + invitation notifications (which may come from teams the user isn't in yet)
    if team:
        qs = Notification.objects.filter(
            Q(team=team, recipient=request.user) |
            Q(recipient=request.user, event_type="team_invitation")
        ).select_related("actor").distinct()
    else:
        qs = Notification.objects.filter(
            recipient=request.user
        ).select_related("actor")

    # Only last 7 days, latest first
    qs = qs.filter(created_at__gte=seven_days_ago).order_by("-created_at")

    unread_count = qs.filter(is_read=False).count()
    notifications = [_serialize_notification(n) for n in qs[:50]]
    return JsonResponse({"ok": True, "notifications": notifications, "unreadCount": unread_count})


@require_POST
@login_required
def api_notifications_read(request):
    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"ok": False, "error": "Invalid JSON"}, status=400)

    if data.get("all"):
        Notification.objects.filter(recipient=request.user, is_read=False).update(is_read=True)
        return JsonResponse({"ok": True})

    notif_id = data.get("id")
    if not notif_id:
        return JsonResponse({"ok": False, "error": "id required"}, status=400)

    Notification.objects.filter(id=notif_id, recipient=request.user).update(is_read=True)
    return JsonResponse({"ok": True})


@require_POST
@login_required
def api_send_deadline_reminders(request):
    """
    Manually trigger deadline reminder emails + in-app notifications.
    Checks tasks due in 0, 1, or 3 days and notifies each assignee once per day.
    """
    from datetime import date, timedelta

    remind_days = [0, 1, 3]
    today = date.today()
    target_dates = [today + timedelta(days=d) for d in remind_days]

    tasks = (
        Task.objects
        .filter(due_date__in=target_dates)
        .select_related("board__workspace__team")
        .prefetch_related("assignees")
    )

    emails_sent = 0
    notifs_created = 0

    for task in tasks:
        try:
            team = task.board.workspace.team
        except Exception:
            continue

        due_date_str = task.due_date.isoformat()
        days_left = (task.due_date - today).days

        assignees = list(task.assignees.all())
        if not assignees:
            continue

        for assignee in assignees:
            assignee_email = assignee.email or assignee.username
            assignee_name = (
                assignee.get_full_name()
                or assignee.first_name
                or assignee.username
            )

            already_notified = Notification.objects.filter(
                team=team,
                recipient=assignee,
                event_type="deadline_reminder",
                target_id=task.id,
                created_at__date=today,
            ).exists()

            if already_notified:
                continue

            if days_left == 0:
                msg = f"⏰ Deadline today: task '{task.title}' assigned by team '{team.name}' is due TODAY."
            elif days_left == 1:
                msg = f"⏰ Deadline tomorrow: task '{task.title}' assigned by team '{team.name}' is due TOMORROW."
            else:
                msg = f"⏰ Upcoming deadline: task '{task.title}' assigned by team '{team.name}' is due in {days_left} day(s) ({due_date_str})."

            Notification.objects.create(
                team=team,
                recipient=assignee,
                actor=None,
                message=msg,
                event_type="deadline_reminder",
                target_tab="tasks",
                target_type="task",
                target_id=task.id,
                extra={
                    "taskName": task.title,
                    "dueDate": due_date_str,
                    "daysLeft": days_left,
                    "teamName": team.name,
                },
            )
            notifs_created += 1

            if assignee_email:
                success = send_deadline_reminder_email(
                    assignee_name=assignee_name,
                    assignee_email=assignee_email,
                    task_title=task.title,
                    team_name=team.name,
                    due_date=due_date_str,
                    days_left=days_left,
                )
                if success:
                    emails_sent += 1

    return JsonResponse({
        "ok": True,
        "notificationsCreated": notifs_created,
        "emailsSent": emails_sent,
    })


