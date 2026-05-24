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
    _get_user_team, _get_team_board, _safe_date_iso, _actor_name,
)

logger = logging.getLogger(__name__)


@login_required
def api_analytics_summary(request):
    team, membership = _get_user_team(request.user)
    if not team:
        return JsonResponse({"ok": True, "tasks": [], "projects": []})

    board = _get_team_board(team)
    columns = list(board.columns.all().order_by("position"))
    col_id_to_board_id = {c.id: i + 1 for i, c in enumerate(columns)}

    tasks = []
    for t in Task.objects.filter(board=board).prefetch_related("assignees"):
        assignee_emails = list(t.assignees.values_list("email", flat=True))
        if assignee_emails and request.user.email not in assignee_emails:
            continue
        tasks.append({
            "id": t.id,
            "name": t.title,
            "priority": t.priority,
            "boardId": col_id_to_board_id.get(t.column_id, 1),
            "dueDate": _safe_date_iso(t.due_date),
        })

    projects = [
        {
            "id": p.id,
            "name": p.name,
            "status": p.status,
        }
        for p in Project.objects.filter(team=team)
    ]

    return JsonResponse({"ok": True, "tasks": tasks, "projects": projects})


@login_required
def api_activity_log(request):
    team, membership = _get_user_team(request.user)
    if not team:
        return JsonResponse({"ok": True, "activities": []})

    qs = ActivityLog.objects.filter(team=team).select_related("actor")[:100]
    activities = []
    for a in qs:
        activities.append({
            "id": a.id,
            "actor": _actor_name(a.actor) if a.actor else "System",
            "action": a.action,
            "targetType": a.target_type,
            "targetId": a.target_id,
            "targetName": a.target_name,
            "detail": a.detail,
            "createdAt": a.created_at.isoformat() if a.created_at else "",
        })
    return JsonResponse({"ok": True, "activities": activities})


@login_required
def api_analytics_enhanced(request):
    """Rich analytics data for Chart.js dashboards."""
    team, membership = _get_user_team(request.user)
    if not team:
        return JsonResponse({"ok": True, "data": {}})

    board = _get_team_board(team)
    columns = list(board.columns.all().order_by("position"))
    tasks_qs = Task.objects.filter(board=board).prefetch_related("assignees")
    all_tasks = list(tasks_qs)
    today = date.today()

    try:
        days = max(1, min(365, int(request.GET.get("days", 14))))
    except (ValueError, TypeError):
        days = 14

    # Optional per-project filter: ?project_id=<id>
    project_filter_id = None
    raw_pid = request.GET.get("project_id")
    if raw_pid not in (None, "", "all", "null"):
        try:
            project_filter_id = int(raw_pid)
        except (TypeError, ValueError):
            project_filter_id = None

    if project_filter_id is not None:
        def _task_pid(t):
            labels = t.labels if isinstance(t.labels, dict) else {}
            pid = labels.get("_projectId")
            try:
                return int(pid) if pid not in (None, "", "null") else None
            except (TypeError, ValueError):
                return None
        all_tasks = [t for t in all_tasks if _task_pid(t) == project_filter_id]

    # Column distribution
    col_data = []
    for col in columns:
        count = sum(1 for t in all_tasks if t.column_id == col.id)
        col_data.append({"name": col.name, "count": count})

    # Priority breakdown
    priority_counts = {"high": 0, "medium": 0, "low": 0}
    for t in all_tasks:
        priority_counts[t.priority] = priority_counts.get(t.priority, 0) + 1

    # Overdue tasks
    overdue = sum(1 for t in all_tasks if t.due_date and t.due_date < today)

    # Tasks created per day (last N days)
    creation_trend = {}
    for i in range(days - 1, -1, -1):
        d = today - timedelta(days=i)
        creation_trend[d.isoformat()] = 0
    for t in all_tasks:
        d = t.created_at.date().isoformat()
        if d in creation_trend:
            creation_trend[d] += 1

    # Completion trend: tasks in last column per day (last N days)
    done_col = columns[-1] if columns else None
    completion_trend = {}
    for i in range(days - 1, -1, -1):
        d = today - timedelta(days=i)
        completion_trend[d.isoformat()] = 0
    if done_col:
        for t in all_tasks:
            if t.column_id == done_col.id:
                d = t.updated_at.date().isoformat()
                if d in completion_trend:
                    completion_trend[d] += 1

    # Member workload
    member_workload = {}
    for t in all_tasks:
        for a in t.assignees.all():
            name = a.get_full_name() or a.first_name or a.username
            member_workload[name] = member_workload.get(name, 0) + 1

    # Project stats (always reflect the whole team, not the filter)
    projects = Project.objects.filter(team=team)
    project_stats = {
        "total": projects.count(),
        "active": projects.filter(status="active").count(),
        "completed": projects.filter(status="completed").count(),
        "archived": projects.filter(status="archived").count(),
    }
    projects_list = [{"id": p.id, "name": p.name, "status": p.status} for p in projects]

    return JsonResponse({"ok": True, "data": {
        "totalTasks": len(all_tasks),
        "overdue": overdue,
        "columns": col_data,
        "priority": priority_counts,
        "creationTrend": creation_trend,
        "completionTrend": completion_trend,
        "memberWorkload": member_workload,
        "projectStats": project_stats,
        "projects": projects_list,
        "activeProjectId": project_filter_id,
    }})


@login_required
def api_calendar_tasks(request):
    """Return all tasks with due dates for calendar view."""
    team, membership = _get_user_team(request.user)
    if not team:
        return JsonResponse({"ok": True, "events": []})

    board = _get_team_board(team)
    columns = list(board.columns.all().order_by("position"))
    col_map = {c.id: c.name for c in columns}
    done_col_id = columns[-1].id if columns else None

    events = []
    for t in Task.objects.filter(board=board, due_date__isnull=False).prefetch_related("assignees"):
        assignees = [a.get_full_name() or a.first_name or a.username for a in t.assignees.all()]
        is_done = t.column_id == done_col_id
        is_overdue = t.due_date < date.today() and not is_done
        events.append({
            "id": t.id,
            "title": t.title,
            "date": t.due_date.isoformat(),
            "priority": t.priority,
            "column": col_map.get(t.column_id, ""),
            "assignees": assignees,
            "done": is_done,
            "overdue": is_overdue,
        })

    return JsonResponse({"ok": True, "events": events})


@login_required
def api_export_csv(request):
    """Export team tasks as CSV."""
    import csv
    from django.http import HttpResponse as DjangoHttpResponse

    team, membership = _get_user_team(request.user)
    if not team:
        return JsonResponse({"ok": False, "error": "No team"}, status=400)

    board = _get_team_board(team)
    columns = list(board.columns.all().order_by("position"))
    col_map = {c.id: c.name for c in columns}

    response = DjangoHttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="taskhive_export_{team.name}.csv"'

    writer = csv.writer(response)
    writer.writerow(["Task", "Description", "Column", "Priority", "Due Date", "Assignees", "Created"])

    for t in Task.objects.filter(board=board).prefetch_related("assignees").order_by("column__position", "position"):
        assignees = ", ".join(a.get_full_name() or a.username for a in t.assignees.all())
        writer.writerow([
            t.title,
            t.description,
            col_map.get(t.column_id, ""),
            t.priority,
            t.due_date.isoformat() if t.due_date else "",
            assignees,
            t.created_at.strftime("%Y-%m-%d"),
        ])

    return response


@login_required
def api_export_pdf(request):
    """Export team tasks as a styled HTML-based PDF report (browser can print-to-PDF)."""
    team, membership = _get_user_team(request.user)
    if not team:
        return JsonResponse({"ok": False, "error": "No team"}, status=400)

    board = _get_team_board(team)
    columns = list(board.columns.all().order_by("position"))
    col_map = {c.id: c.name for c in columns}
    today = date.today()

    tasks = list(Task.objects.filter(board=board).prefetch_related("assignees").order_by("column__position", "position"))

    # Build summary stats
    total = len(tasks)
    by_col = {}
    for c in columns:
        by_col[c.name] = sum(1 for t in tasks if t.column_id == c.id)
    overdue = sum(1 for t in tasks if t.due_date and t.due_date < today)
    high_p = sum(1 for t in tasks if t.priority == "high")

    # Build task rows HTML
    rows_html = ""
    for t in tasks:
        assignees = ", ".join(a.get_full_name() or a.username for a in t.assignees.all())
        p_color = {"high": "#f87171", "medium": "#fbbf24", "low": "#4ade80"}.get(t.priority, "#9ca3af")
        rows_html += f"""<tr>
            <td>{t.title}</td>
            <td>{col_map.get(t.column_id, '')}</td>
            <td style="color:{p_color};font-weight:600">{t.priority}</td>
            <td>{t.due_date.isoformat() if t.due_date else '-'}</td>
            <td>{assignees or '-'}</td>
        </tr>"""

    col_summary = " | ".join(f"{name}: {count}" for name, count in by_col.items())

    html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>TaskHive Report - {team.name}</title>
<style>
  body {{ font-family: 'Segoe UI', sans-serif; margin: 40px; color: #1a1a2e; }}
  h1 {{ color: #0f3460; border-bottom: 2px solid #0f3460; padding-bottom: 8px; }}
  .stats {{ display: flex; gap: 20px; margin: 20px 0; }}
  .stat-card {{ background: #f0f4ff; border-radius: 8px; padding: 16px 24px; text-align: center; }}
  .stat-card .num {{ font-size: 28px; font-weight: 700; color: #0f3460; }}
  .stat-card .label {{ font-size: 12px; color: #666; margin-top: 4px; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 20px; font-size: 13px; }}
  th {{ background: #0f3460; color: #fff; padding: 10px 8px; text-align: left; }}
  td {{ padding: 8px; border-bottom: 1px solid #e0e0e0; }}
  tr:nth-child(even) {{ background: #f8f9ff; }}
  .footer {{ margin-top: 30px; font-size: 11px; color: #999; text-align: center; }}
  @media print {{ body {{ margin: 20px; }} }}
</style></head>
<body>
  <h1>TaskHive Report: {team.name}</h1>
  <p style="color:#666;font-size:13px;">Generated on {today.isoformat()} | {col_summary}</p>
  <div class="stats">
    <div class="stat-card"><div class="num">{total}</div><div class="label">Total Tasks</div></div>
    <div class="stat-card"><div class="num" style="color:#4ade80">{by_col.get(columns[-1].name, 0) if columns else 0}</div><div class="label">Completed</div></div>
    <div class="stat-card"><div class="num" style="color:#f87171">{overdue}</div><div class="label">Overdue</div></div>
    <div class="stat-card"><div class="num" style="color:#fbbf24">{high_p}</div><div class="label">High Priority</div></div>
  </div>
  <table>
    <thead><tr><th>Task</th><th>Column</th><th>Priority</th><th>Due Date</th><th>Assignees</th></tr></thead>
    <tbody>{rows_html}</tbody>
  </table>
  <div class="footer">TaskHive &mdash; Project Management Report</div>
</body></html>"""

    from django.http import HttpResponse as DjangoHttpResponse
    response = DjangoHttpResponse(html, content_type="text/html")
    response["Content-Disposition"] = f'attachment; filename="taskhive_report_{team.name}.html"'
    return response


