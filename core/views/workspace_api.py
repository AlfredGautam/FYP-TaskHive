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
from core.file_validation import validate_attachment
from core.sanitize import sanitize_text

logger = logging.getLogger(__name__)


def _get_user_team(user):
    profile, _ = UserProfile.objects.get_or_create(user=user)
    if not profile.current_team_id:
        return None, None
    team = Team.objects.filter(id=profile.current_team_id).first()
    if not team:
        return None, None
    membership = TeamMembership.objects.filter(team=team, user=user).first()
    if not membership:
        return None, None
    return team, membership


def _get_team_workspace(team):
    ws = Workspace.objects.filter(team=team).first()
    if not ws:
        ws = Workspace.objects.create(team=team, name=f"{team.name} Workspace", created_by=None)
        board = Board.objects.create(workspace=ws, name="Main Board", created_by=None)
        Column.objects.create(board=board, name="To Do", position=1)
        Column.objects.create(board=board, name="In Progress", position=2)
        Column.objects.create(board=board, name="Done", position=3)
    return ws


def _get_team_board(team):
    ws = _get_team_workspace(team)
    board = Board.objects.filter(workspace=ws).first()
    if not board:
        board = Board.objects.create(workspace=ws, name="Main Board", created_by=None)
        Column.objects.create(board=board, name="To Do", position=1)
        Column.objects.create(board=board, name="In Progress", position=2)
        Column.objects.create(board=board, name="Done", position=3)
    return board


def _safe_date_iso(value):
    if not value:
        return ""
    try:
        return value.isoformat()
    except Exception:
        return str(value)


def _actor_name(user):
    return (user.get_full_name() or user.first_name or user.username or user.email or "Someone")


def _parse_mentions(body, team):
    """Return list of User objects @mentioned in body, restricted to team members.

    Supports matching by:
      - full email (alice@example.com)
      - email prefix before @ (alice)
      - display name without spaces (alicesmith)
      - public username (from UserProfile.username_public)
    """
    if not body or not team:
        return []
    tokens = set(m.group(1).lower() for m in _MENTION_RE.finditer(body))
    if not tokens:
        return []
    memberships = TeamMembership.objects.filter(team=team).select_related("user")
    matched = []
    seen_ids = set()
    for mship in memberships:
        u = mship.user
        if not u or u.id in seen_ids:
            continue
        email = (u.email or u.username or "").lower()
        email_prefix = email.split("@")[0] if "@" in email else email
        display_squashed = (u.get_full_name() or "").lower().replace(" ", "")
        username_public = ""
        try:
            username_public = (u.profile.username_public or "").lower()
        except Exception:
            pass
        candidates = {c for c in (email, email_prefix, display_squashed, username_public) if c}
        if tokens & candidates:
            matched.append(u)
            seen_ids.add(u.id)
    return matched


def _notify_team(
    team,
    actor,
    message,
    *,
    event_type="",
    target_tab="",
    target_type="",
    target_id=None,
    extra=None,
):
    memberships = TeamMembership.objects.filter(team=team).select_related("user")
    now = timezone.now()
    payload = extra if isinstance(extra, dict) else {}
    notifs = [
        Notification(
            team=team,
            recipient=m.user,
            actor=actor,
            message=message,
            event_type=event_type,
            target_tab=target_tab,
            target_type=target_type,
            target_id=target_id,
            extra=payload,
            created_at=now,
        )
        for m in memberships
    ]
    if notifs:
        Notification.objects.bulk_create(notifs)

    # Real-time WebSocket push
    from core.ws_utils import broadcast_notification
    broadcast_notification(team.id, {"message": message, "event_type": event_type})


def _log_activity(team, actor, action, target_type="", target_id=None, target_name="", detail=""):
    ActivityLog.objects.create(
        team=team,
        actor=actor,
        action=action,
        target_type=target_type,
        target_id=target_id,
        target_name=target_name,
        detail=detail,
    )

    # Real-time WebSocket push — tell clients to refresh data
    from core.ws_utils import broadcast_data_changed
    broadcast_data_changed(team.id, {"action": action, "target_type": target_type})


# ---------------------------------------------------------------
# Audit-style change tracking helpers
# ---------------------------------------------------------------

# Human-readable labels for choice fields
_PRIORITY_LABELS = {
    Task.PRIORITY_HIGH: "High",
    Task.PRIORITY_MEDIUM: "Medium",
    Task.PRIORITY_LOW: "Low",
}
_PROJECT_STATUS_LABELS = {
    Project.STATUS_ACTIVE: "Active",
    Project.STATUS_COMPLETED: "Completed",
    Project.STATUS_ARCHIVED: "Archived",
}
_TASK_TYPE_LABELS = {
    Task.TYPE_NORMAL: "Normal",
    Task.TYPE_SUPER: "Super",
}


def _label_priority(value):
    return _PRIORITY_LABELS.get((value or "").lower(), value or "—")


def _label_project_status(value):
    return _PROJECT_STATUS_LABELS.get((value or "").lower(), value or "—")


def _label_task_type(value):
    return _TASK_TYPE_LABELS.get((value or "").lower(), value or "—")


def _label_date(value):
    if not value:
        return "no date"
    try:
        return value.isoformat() if hasattr(value, "isoformat") else str(value)
    except Exception:
        return str(value)


def _emit_change(team, actor, message, *, event_type, target_type, target_id, target_name, extra=None):
    """Send a single audit-style notification + activity log entry.

    `message` should already include actor name and be human-readable, e.g.
        "Alfred changed task 'UI Design' priority from 'Medium' to 'High'"
    """
    payload = dict(extra or {})
    payload.setdefault("targetName", target_name)
    _notify_team(
        team, actor, message,
        event_type=event_type,
        target_tab="tasks" if target_type == "task" else ("projects" if target_type == "project" else ""),
        target_type=target_type,
        target_id=target_id,
        extra=payload,
    )
    _log_activity(team, actor, event_type, target_type, target_id, target_name, message)


def _diff_task_changes(actor, old_state, new_state, columns_by_id):
    """Compare old/new task states; return list of audit messages (without leading actor name).

    old_state / new_state: dicts with keys: title, description, priority, due_date,
        column_id, task_type, is_blocked, assignee_emails (sorted set/list).
    columns_by_id: {column_id: name} map for resolving column moves.

    Returns list of (event_type, fragment) tuples — fragment is the text after the actor name.
    """
    changes = []
    title_for_msg = new_state.get("title") or old_state.get("title") or ""

    # Title rename
    if old_state.get("title") != new_state.get("title"):
        changes.append((
            "task_renamed",
            f"renamed task from '{old_state.get('title')}' to '{new_state.get('title')}'",
        ))

    # Priority
    if old_state.get("priority") != new_state.get("priority"):
        changes.append((
            "task_priority_changed",
            f"changed task '{title_for_msg}' priority from '{_label_priority(old_state.get('priority'))}' to '{_label_priority(new_state.get('priority'))}'",
        ))

    # Column / status
    if old_state.get("column_id") != new_state.get("column_id"):
        old_col = columns_by_id.get(old_state.get("column_id"), "—")
        new_col = columns_by_id.get(new_state.get("column_id"), "—")
        changes.append((
            "task_moved",
            f"moved task '{title_for_msg}' from '{old_col}' to '{new_col}'",
        ))

    # Due date
    if old_state.get("due_date") != new_state.get("due_date"):
        changes.append((
            "task_due_changed",
            f"changed task '{title_for_msg}' due date from '{_label_date(old_state.get('due_date'))}' to '{_label_date(new_state.get('due_date'))}'",
        ))

    # Task type
    if old_state.get("task_type") != new_state.get("task_type"):
        changes.append((
            "task_type_changed",
            f"changed task '{title_for_msg}' type from '{_label_task_type(old_state.get('task_type'))}' to '{_label_task_type(new_state.get('task_type'))}'",
        ))

    # Blocked flag
    if bool(old_state.get("is_blocked")) != bool(new_state.get("is_blocked")):
        if new_state.get("is_blocked"):
            changes.append(("task_blocked", f"marked task '{title_for_msg}' as blocked"))
        else:
            changes.append(("task_unblocked", f"unblocked task '{title_for_msg}'"))

    # Description (just say it was edited; full diff is too noisy)
    old_desc = (old_state.get("description") or "").strip()
    new_desc = (new_state.get("description") or "").strip()
    if old_desc != new_desc:
        changes.append((
            "task_description_changed",
            f"updated description of task '{title_for_msg}'",
        ))

    # Assignees: added / removed
    old_assignees = set(old_state.get("assignee_emails") or [])
    new_assignees = set(new_state.get("assignee_emails") or [])
    added = sorted(new_assignees - old_assignees)
    removed = sorted(old_assignees - new_assignees)
    if added:
        changes.append((
            "task_assigned",
            f"assigned task '{title_for_msg}' to {', '.join(added)}",
        ))
    if removed:
        changes.append((
            "task_unassigned",
            f"unassigned {', '.join(removed)} from task '{title_for_msg}'",
        ))

    return changes


def _diff_project_changes(old_state, new_state):
    """Compare old/new project states. Returns list of (event_type, fragment) tuples."""
    changes = []
    name_for_msg = new_state.get("name") or old_state.get("name") or ""

    if old_state.get("name") != new_state.get("name"):
        changes.append((
            "project_renamed",
            f"renamed project from '{old_state.get('name')}' to '{new_state.get('name')}'",
        ))

    if old_state.get("status") != new_state.get("status"):
        changes.append((
            "project_status_changed",
            f"changed project '{name_for_msg}' status from '{_label_project_status(old_state.get('status'))}' to '{_label_project_status(new_state.get('status'))}'",
        ))

    old_desc = (old_state.get("description") or "").strip()
    new_desc = (new_state.get("description") or "").strip()
    if old_desc != new_desc:
        changes.append((
            "project_description_changed",
            f"updated description of project '{name_for_msg}'",
        ))

    old_members = set(old_state.get("members") or [])
    new_members = set(new_state.get("members") or [])
    added = sorted(new_members - old_members)
    removed = sorted(old_members - new_members)
    if added:
        changes.append((
            "project_member_added",
            f"added {', '.join(added)} to project '{name_for_msg}'",
        ))
    if removed:
        changes.append((
            "project_member_removed",
            f"removed {', '.join(removed)} from project '{name_for_msg}'",
        ))

    return changes


def _serialize_notification(n):
    return {
        "id": n.id,
        "message": n.message,
        "eventType": n.event_type,
        "isRead": n.is_read,
        "targetTab": n.target_tab,
        "targetType": n.target_type,
        "targetId": n.target_id,
        "extra": n.extra if isinstance(n.extra, dict) else {},
        "createdAt": n.created_at.isoformat() if n.created_at else "",
        "actor": _actor_name(n.actor) if n.actor else "",
    }


def _task_to_dict(task):
    board = task.board
    columns = list(board.columns.all().order_by("position"))
    col_index = 1
    for i, c in enumerate(columns):
        if c.id == task.column_id:
            col_index = i + 1
            break
    assignee_emails = list(task.assignees.values_list("email", flat=True))
    code_meta = {}
    if task.labels and isinstance(task.labels, dict):
        code_meta = task.labels
    elif task.labels and isinstance(task.labels, list) and len(task.labels) > 0 and isinstance(task.labels[0], dict):
        code_meta = task.labels[0]
    return {
        "id": task.id,
        "name": task.title,
        "description": task.description,
        "priority": task.priority,
        "dueDate": _safe_date_iso(task.due_date),
        "assignees": assignee_emails,
        "boardId": col_index,
        "projectId": None,
        "taskType": task.task_type,
        "codeMeta": code_meta,
        "blockedBy": list(task.blocked_by.values_list("id", flat=True)),
    }


@login_required
def api_workspace_load(request):
    team, membership = _get_user_team(request.user)
    if not team:
        return JsonResponse({"ok": True, "tasks": [], "projects": [], "files": [], "approvalRequests": []})

    board = _get_team_board(team)
    columns = list(board.columns.all().order_by("position"))

    col_id_to_board_id = {}
    for i, c in enumerate(columns):
        col_id_to_board_id[c.id] = i + 1

    tasks_qs = Task.objects.filter(board=board).select_related("column").prefetch_related("assignees", "blocked_by").order_by("column__position", "position", "-updated_at")[:500]
    tasks_list = []
    for t in tasks_qs:
        assignee_emails = list(t.assignees.values_list("email", flat=True))
        # Visibility rule: if explicitly assigned, only assigned members see it.
        if assignee_emails and (request.user.email not in assignee_emails):
            continue

        code_meta = {}
        if t.labels and isinstance(t.labels, dict):
            code_meta = t.labels
        elif t.labels and isinstance(t.labels, list) and len(t.labels) > 0 and isinstance(t.labels[0], dict):
            code_meta = t.labels[0]

        project_id = None
        if code_meta and code_meta.get("_projectId"):
            project_id = code_meta["_projectId"]

        tasks_list.append({
            "id": t.id,
            "name": t.title,
            "description": t.description,
            "priority": t.priority,
            "dueDate": _safe_date_iso(t.due_date),
            "assignees": assignee_emails,
            "boardId": col_id_to_board_id.get(t.column_id, 1),
            "projectId": project_id,
            "taskType": t.task_type,
            "codeMeta": code_meta,
            "blocked": t.is_blocked,
            "blockedBy": [b.id for b in t.blocked_by.all()],
        })

    projects_qs = Project.objects.filter(team=team)
    projects_list = [
        {
            "id": p.id,
            "name": p.name,
            "description": p.description,
            "status": p.status,
            "members": p.members if isinstance(p.members, list) else [],
        }
        for p in projects_qs
    ]

    files_qs = ProjectFile.objects.filter(team=team)
    files_list = [
        {
            "id": f.id,
            "name": f.name,
            "type": f.file_type,
            "size": f.size,
            "uploaded": f.created_at.strftime("%Y-%m-%d") if f.created_at else "",
            "content": f.file.url if f.file else "",
        }
        for f in files_qs
    ]

    approvals_qs = ApprovalRequest.objects.filter(team=team)
    approvals_list = [
        {
            "id": a.id,
            "entityType": a.entity_type,
            "action": a.action,
            "payload": a.payload,
            "targetId": a.target_id,
            "summary": a.summary,
            "requestedBy": a.requested_by_name,
            "requestedAt": a.created_at.isoformat() if a.created_at else "",
        }
        for a in approvals_qs
    ]

    return JsonResponse({
        "ok": True,
        "tasks": tasks_list,
        "projects": projects_list,
        "files": files_list,
        "approvalRequests": approvals_list,
    })


@require_POST
@login_required
def api_workspace_task_save(request):
    team, membership = _get_user_team(request.user)
    if not team:
        return JsonResponse({"ok": False, "error": "No team"}, status=400)

    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"ok": False, "error": "Invalid JSON"}, status=400)

    task_id = data.get("id")
    name = sanitize_text((data.get("name") or "").strip(), 300)
    if not name:
        return JsonResponse({"ok": False, "error": "Task name required"}, status=400)

    board = _get_team_board(team)
    columns = list(board.columns.all().order_by("position"))

    board_id_fe = data.get("boardId", 1)
    if isinstance(board_id_fe, int) and 1 <= board_id_fe <= len(columns):
        column = columns[board_id_fe - 1]
    else:
        column = columns[0]

    due_date_raw = data.get("dueDate")
    due_date = None
    if isinstance(due_date_raw, str):
        due_date_raw = due_date_raw.strip()
        if due_date_raw:
            try:
                due_date = date.fromisoformat(due_date_raw)
            except ValueError:
                return JsonResponse({"ok": False, "error": "Invalid dueDate format. Use YYYY-MM-DD."}, status=400)
    elif due_date_raw:
        due_date = due_date_raw

    code_meta = data.get("codeMeta") or {}
    # Always record projectId from payload (use key presence to decide).
    # Coerce to int when possible so filtering is consistent across load/save.
    if "projectId" in data:
        raw_pid = data.get("projectId")
        try:
            project_id = int(raw_pid) if raw_pid not in (None, "", "null") else None
        except (TypeError, ValueError):
            project_id = None
        if project_id is None:
            code_meta.pop("_projectId", None)
        else:
            code_meta["_projectId"] = project_id
    else:
        project_id = code_meta.get("_projectId")

    is_update = bool(task_id)
    old_assignee_ids = set()
    old_state = None
    if task_id:
        try:
            task = Task.objects.get(id=task_id, board=board)
        except Task.DoesNotExist:
            return JsonResponse({"ok": False, "error": "Task not found"}, status=404)
        # Capture full old state before any modification (used for audit-style diff notifications)
        old_assignee_ids = set(task.assignees.values_list("id", flat=True))
        old_state = {
            "title": task.title,
            "description": task.description,
            "priority": task.priority,
            "due_date": _safe_date_iso(task.due_date),
            "column_id": task.column_id,
            "task_type": task.task_type,
            "is_blocked": task.is_blocked,
            "assignee_emails": sorted(task.assignees.values_list("email", flat=True)),
        }
        task.title = name
        task.description = data.get("description", "")
        task.priority = data.get("priority", "medium")
        task.due_date = due_date
        task.task_type = data.get("taskType", "normal")
        task.column = column
        task.labels = code_meta
        task.is_blocked = bool(data.get("blocked", False))
        task.save()
    else:
        task = Task.objects.create(
            board=board,
            column=column,
            title=name,
            description=data.get("description", ""),
            priority=data.get("priority", "medium"),
            due_date=due_date,
            task_type=data.get("taskType", "normal"),
            labels=code_meta,
            is_blocked=bool(data.get("blocked", False)),
            created_by=request.user,
        )

    # --- Task dependencies (blocked_by) ---
    if "blockedBy" in data:
        raw_ids = data.get("blockedBy") or []
        try:
            blocker_ids = [int(x) for x in raw_ids if x is not None]
        except (TypeError, ValueError):
            blocker_ids = []
        # Restrict to tasks on the same board; drop self-reference
        valid_blocker_ids = list(
            Task.objects.filter(id__in=blocker_ids, board=board)
            .exclude(id=task.id)
            .values_list("id", flat=True)
        )
        task.blocked_by.set(valid_blocker_ids)

    # Only team admins (head) can assign tasks. Regular members cannot
    # change assignees; their assignees field in the payload is ignored
    # and any existing assignees are preserved.
    is_admin = (membership.role == TeamMembership.ROLE_HEAD)
    new_assignee_users = []

    if is_admin:
        task.assignees.clear()
        assignees = data.get("assignees", [])
        if assignees:
            new_assignee_users = list(User.objects.filter(
                id__in=TeamMembership.objects.filter(
                    team=team,
                    user__email__in=assignees,
                ).values_list("user_id", flat=True)
            ))
            task.assignees.set(new_assignee_users)
    else:
        # Non-admins: keep existing assignees (for updates), no assignees on create
        new_assignee_users = list(task.assignees.all())

    # Determine which assignees are truly new (not previously assigned)
    truly_new_assignee_users = [u for u in new_assignee_users if u.id not in old_assignee_ids]

    actor_display = _actor_name(request.user)

    if is_update and old_state is not None:
        # Build new_state from the post-save task and emit one audit notification per real change
        new_state = {
            "title": task.title,
            "description": task.description,
            "priority": task.priority,
            "due_date": _safe_date_iso(task.due_date),
            "column_id": task.column_id,
            "task_type": task.task_type,
            "is_blocked": task.is_blocked,
            "assignee_emails": sorted(task.assignees.values_list("email", flat=True)),
        }
        columns_by_id = {c.id: c.name for c in columns}
        change_list = _diff_task_changes(request.user, old_state, new_state, columns_by_id)

        if change_list:
            for event_type, fragment in change_list:
                _emit_change(
                    team, request.user,
                    f"{actor_display} {fragment}",
                    event_type=event_type,
                    target_type="task",
                    target_id=task.id,
                    target_name=task.title,
                )
        else:
            # No diffable changes detected (rare — e.g. only blocked_by deps changed). Fall back to a generic message.
            _emit_change(
                team, request.user,
                f"{actor_display} updated task '{task.title}'",
                event_type="task_updated",
                target_type="task",
                target_id=task.id,
                target_name=task.title,
            )
    else:
        # Creation
        _emit_change(
            team, request.user,
            f"{actor_display} created task '{task.title}'",
            event_type="task_created",
            target_type="task",
            target_id=task.id,
            target_name=task.title,
        )

    actor_name = _actor_name(request.user)
    due_str = _safe_date_iso(task.due_date)
    # On update: only email newly added assignees. On create: email all assignees.
    email_targets = truly_new_assignee_users if is_update else new_assignee_users
    logger.info(
        "Task '%s' saved (is_update=%s). email_targets=%d, assignees_payload=%s",
        task.title, is_update, len(email_targets),
        [u.email for u in email_targets],
    )
    for assignee_user in email_targets:
        assignee_email = assignee_user.email or assignee_user.username
        if assignee_email and assignee_email != (request.user.email or request.user.username):
            assignee_name = assignee_user.get_full_name() or assignee_user.first_name or assignee_user.username
            logger.info("Sending task-assigned email to %s for task '%s'", assignee_email, task.title)
            ok = send_task_assigned_email(
                assignee_name=assignee_name,
                assignee_email=assignee_email,
                task_title=task.title,
                team_name=team.name,
                assigned_by_name=actor_name,
                due_date=due_str,
                priority=task.priority,
            )
            if not ok:
                logger.error("send_task_assigned_email FAILED for %s on task '%s'", assignee_email, task.title)
        else:
            logger.info(
                "Skipped email for assignee %s (same as requester or empty)",
                assignee_user.email,
            )

    col_id_to_board_id = {}
    for i, c in enumerate(columns):
        col_id_to_board_id[c.id] = i + 1

    return JsonResponse({
        "ok": True,
        "task": {
            "id": task.id,
            "name": task.title,
            "description": task.description,
            "priority": task.priority,
            "dueDate": _safe_date_iso(task.due_date),
            "assignees": list(task.assignees.values_list("email", flat=True)),
            "boardId": col_id_to_board_id.get(task.column_id, 1),
            "projectId": project_id,
            "taskType": task.task_type,
            "codeMeta": code_meta,
            "blocked": task.is_blocked,
            "blockedBy": list(task.blocked_by.values_list("id", flat=True)),
        }
    })


@require_POST
@login_required
def api_workspace_task_delete(request):
    team, membership = _get_user_team(request.user)
    if not team:
        return JsonResponse({"ok": False, "error": "No team"}, status=400)

    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"ok": False, "error": "Invalid JSON"}, status=400)

    task_id = data.get("id")
    if not task_id:
        return JsonResponse({"ok": False, "error": "id required"}, status=400)

    board = _get_team_board(team)
    task = Task.objects.filter(id=task_id, board=board).first()
    if task:
        task_name = task.title
        task.delete()
        _notify_team(
            team,
            request.user,
            f"{_actor_name(request.user)} deleted task '{task_name}'.",
            event_type="task_deleted",
            target_tab="tasks",
            target_type="task",
            target_id=task_id,
            extra={"taskName": task_name},
        )
        _log_activity(team, request.user, "deleted", "task", task_id, task_name,
                      f"{_actor_name(request.user)} deleted task '{task_name}'")
    return JsonResponse({"ok": True})


@require_POST
@login_required
def api_workspace_task_move(request):
    team, membership = _get_user_team(request.user)
    if not team:
        return JsonResponse({"ok": False, "error": "No team"}, status=400)

    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"ok": False, "error": "Invalid JSON"}, status=400)

    task_id = data.get("id")
    board_id_fe = data.get("boardId", 1)

    board = _get_team_board(team)
    columns = list(board.columns.all().order_by("position"))

    try:
        task = Task.objects.get(id=task_id, board=board)
    except Task.DoesNotExist:
        return JsonResponse({"ok": False, "error": "Task not found"}, status=404)

    if isinstance(board_id_fe, int) and 1 <= board_id_fe <= len(columns):
        target_column = columns[board_id_fe - 1]
        # No-op guard: task already in the target column -> skip write, notification, activity log.
        if task.column_id == target_column.id:
            return JsonResponse({"ok": True, "noop": True})

        # Capture source column name BEFORE the move for an audit-style "from X to Y" message
        from_column_name = task.column.name if task.column else "—"
        task.column = target_column
        task.save(update_fields=["column"])
        actor_display = _actor_name(request.user)
        _emit_change(
            team, request.user,
            f"{actor_display} moved task '{task.title}' from '{from_column_name}' to '{task.column.name}'",
            event_type="task_moved",
            target_type="task",
            target_id=task.id,
            target_name=task.title,
            extra={"fromColumn": from_column_name, "toColumn": task.column.name},
        )

    return JsonResponse({"ok": True})


@require_POST
@login_required
def api_workspace_project_save(request):
    team, membership = _get_user_team(request.user)
    if not team:
        return JsonResponse({"ok": False, "error": "No team"}, status=400)

    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"ok": False, "error": "Invalid JSON"}, status=400)

    proj_id = data.get("id")
    name = (data.get("name") or "").strip()
    if not name:
        return JsonResponse({"ok": False, "error": "Project name required"}, status=400)

    valid_statuses = {Project.STATUS_ACTIVE, Project.STATUS_COMPLETED, Project.STATUS_ARCHIVED}
    incoming_status = (data.get("status") or Project.STATUS_ACTIVE).strip().lower()
    if incoming_status not in valid_statuses:
        incoming_status = Project.STATUS_ACTIVE

    team_member_emails = {
        (e or "").lower()
        for e in TeamMembership.objects.filter(team=team)
        .select_related("user")
        .values_list("user__email", flat=True)
    }
    incoming_members = data.get("members", [])
    if not isinstance(incoming_members, list):
        incoming_members = []
    cleaned_members = []
    seen = set()
    for m in incoming_members:
        email = (str(m or "").strip().lower())
        if not email or email not in team_member_emails or email in seen:
            continue
        cleaned_members.append(email)
        seen.add(email)

    is_update = bool(proj_id)
    old_state = None
    if proj_id:
        try:
            project = Project.objects.get(id=proj_id, team=team)
        except Project.DoesNotExist:
            return JsonResponse({"ok": False, "error": "Project not found"}, status=404)
        # Capture full old state before any modification
        old_state = {
            "name": project.name,
            "description": project.description,
            "status": project.status,
            "members": list(project.members) if isinstance(project.members, list) else [],
        }
        project.name = name
        project.description = data.get("description", "")
        project.status = incoming_status
        project.members = cleaned_members
        project.save()
    else:
        project = Project.objects.create(
            team=team,
            name=name,
            description=data.get("description", ""),
            status=incoming_status,
            members=cleaned_members,
            created_by=request.user,
        )

    actor_display = _actor_name(request.user)

    if is_update and old_state is not None:
        new_state = {
            "name": project.name,
            "description": project.description,
            "status": project.status,
            "members": list(project.members) if isinstance(project.members, list) else [],
        }
        change_list = _diff_project_changes(old_state, new_state)
        if change_list:
            for event_type, fragment in change_list:
                _emit_change(
                    team, request.user,
                    f"{actor_display} {fragment}",
                    event_type=event_type,
                    target_type="project",
                    target_id=project.id,
                    target_name=project.name,
                )
        else:
            _emit_change(
                team, request.user,
                f"{actor_display} updated project '{project.name}'",
                event_type="project_updated",
                target_type="project",
                target_id=project.id,
                target_name=project.name,
            )
    else:
        _emit_change(
            team, request.user,
            f"{actor_display} created project '{project.name}'",
            event_type="project_created",
            target_type="project",
            target_id=project.id,
            target_name=project.name,
        )

    return JsonResponse({
        "ok": True,
        "project": {
            "id": project.id,
            "name": project.name,
            "description": project.description,
            "status": project.status,
            "members": project.members if isinstance(project.members, list) else [],
        }
    })


@require_POST
@login_required
def api_workspace_project_delete(request):
    team, membership = _get_user_team(request.user)
    if not team:
        return JsonResponse({"ok": False, "error": "No team"}, status=400)

    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"ok": False, "error": "Invalid JSON"}, status=400)

    proj_id = data.get("id")
    if not proj_id:
        return JsonResponse({"ok": False, "error": "id required"}, status=400)

    project = Project.objects.filter(id=proj_id, team=team).first()

    board = _get_team_board(team)
    for t in Task.objects.filter(board=board):
        labels = t.labels if isinstance(t.labels, dict) else {}
        if str(labels.get("_projectId")) == str(proj_id):
            labels.pop("_projectId", None)
            t.labels = labels
            t.save(update_fields=["labels"])

    Project.objects.filter(id=proj_id, team=team).delete()
    if project:
        _notify_team(
            team,
            request.user,
            f"{_actor_name(request.user)} deleted project '{project.name}'.",
            event_type="project_deleted",
            target_tab="projects",
            target_type="project",
            target_id=project.id,
            extra={"projectName": project.name},
        )
        _log_activity(team, request.user, "deleted", "project", project.id, project.name,
                      f"{_actor_name(request.user)} deleted project '{project.name}'")
    return JsonResponse({"ok": True})


@require_POST
@login_required
def api_workspace_file_upload(request):
    team, membership = _get_user_team(request.user)
    if not team:
        return JsonResponse({"ok": False, "error": "No team"}, status=400)

    up = request.FILES.get("file")
    if not up:
        return JsonResponse({"ok": False, "error": "No file"}, status=400)

    err = validate_attachment(up)
    if err:
        return JsonResponse({"ok": False, "error": err}, status=400)

    ext = up.name.rsplit(".", 1)[-1].lower() if "." in up.name else ""
    type_map = {
        "pdf": "pdf", "doc": "document", "docx": "document", "txt": "document",
        "png": "image", "jpg": "image", "jpeg": "image", "gif": "image", "svg": "image",
        "zip": "archive", "rar": "archive", "7z": "archive",
        "mp4": "video", "mov": "video", "avi": "video",
        "mp3": "audio", "wav": "audio",
    }
    file_type = type_map.get(ext, "file")

    def fmt_size(n):
        if n < 1024:
            return f"{n} B"
        elif n < 1024 * 1024:
            return f"{n / 1024:.1f} KB"
        else:
            return f"{n / (1024 * 1024):.1f} MB"

    pf = ProjectFile.objects.create(
        team=team,
        name=up.name,
        file_type=file_type,
        size=fmt_size(up.size),
        file=up,
        uploaded_by=request.user,
    )

    _notify_team(
        team,
        request.user,
        f"{_actor_name(request.user)} uploaded file '{pf.name}'.",
        event_type="file_uploaded",
        target_tab="files",
        target_type="file",
        target_id=pf.id,
        extra={"fileName": pf.name},
    )

    return JsonResponse({
        "ok": True,
        "file": {
            "id": pf.id,
            "name": pf.name,
            "type": pf.file_type,
            "size": pf.size,
            "uploaded": pf.created_at.strftime("%Y-%m-%d") if pf.created_at else "",
            "content": pf.file.url if pf.file else "",
        }
    })


@require_POST
@login_required
def api_workspace_file_delete(request):
    team, membership = _get_user_team(request.user)
    if not team:
        return JsonResponse({"ok": False, "error": "No team"}, status=400)

    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"ok": False, "error": "Invalid JSON"}, status=400)

    file_id = data.get("id")
    if not file_id:
        return JsonResponse({"ok": False, "error": "id required"}, status=400)

    project_file = ProjectFile.objects.filter(id=file_id, team=team).first()
    if project_file:
        file_name = project_file.name
        project_file.delete()
        _notify_team(
            team,
            request.user,
            f"{_actor_name(request.user)} deleted file '{file_name}'.",
            event_type="file_deleted",
            target_tab="files",
            target_type="file",
            target_id=file_id,
            extra={"fileName": file_name},
        )
    return JsonResponse({"ok": True})


@require_POST
@login_required
def api_workspace_approval_add(request):
    team, membership = _get_user_team(request.user)
    if not team:
        return JsonResponse({"ok": False, "error": "No team"}, status=400)

    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"ok": False, "error": "Invalid JSON"}, status=400)

    entity_type = data.get("entityType", "")
    action = data.get("action", "")
    payload = data.get("payload", {})
    target_id = data.get("targetId")
    summary = data.get("summary", "")
    requested_by_name = data.get("requestedBy", "")

    ar = ApprovalRequest.objects.create(
        team=team,
        entity_type=entity_type,
        action=action,
        payload=payload,
        target_id=target_id,
        summary=summary,
        requested_by=request.user,
        requested_by_name=requested_by_name,
    )

    _notify_team(
        team,
        request.user,
        f"{_actor_name(request.user)} requested approval: {summary or action}",
        event_type="approval_requested",
        target_tab="tasks" if entity_type == "task" else "projects",
        target_type=entity_type,
        target_id=target_id,
        extra={"summary": summary, "action": action},
    )

    return JsonResponse({
        "ok": True,
        "approval": {
            "id": ar.id,
            "entityType": ar.entity_type,
            "action": ar.action,
            "payload": ar.payload,
            "targetId": ar.target_id,
            "summary": ar.summary,
            "requestedBy": ar.requested_by_name,
            "requestedAt": ar.created_at.isoformat() if ar.created_at else "",
        }
    })


@require_POST
@login_required
def api_workspace_approval_resolve(request):
    team, membership = _get_user_team(request.user)
    if not team:
        return JsonResponse({"ok": False, "error": "No team"}, status=400)

    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"ok": False, "error": "Invalid JSON"}, status=400)

    ar_id = data.get("id")
    if not ar_id:
        return JsonResponse({"ok": False, "error": "id required"}, status=400)

    ar = ApprovalRequest.objects.filter(id=ar_id, team=team).first()
    ApprovalRequest.objects.filter(id=ar_id, team=team).delete()
    if ar:
        _notify_team(
            team,
            request.user,
            f"{_actor_name(request.user)} resolved approval request: {ar.summary or ar.action}.",
            event_type="approval_resolved",
            target_tab="tasks" if ar.entity_type == "task" else "projects",
            target_type=ar.entity_type,
            target_id=ar.target_id,
            extra={"summary": ar.summary, "action": ar.action},
        )
    return JsonResponse({"ok": True})


@login_required
def api_task_comments(request, task_id):
    team, membership = _get_user_team(request.user)
    if not team:
        return JsonResponse({"ok": False, "error": "No team"}, status=400)

    board = _get_team_board(team)
    task = Task.objects.filter(id=task_id, board=board).first()
    if not task:
        return JsonResponse({"ok": False, "error": "Task not found"}, status=404)

    comments = TaskComment.objects.filter(task=task).select_related("author")
    data = []
    for c in comments:
        data.append({
            "id": c.id,
            "body": c.body,
            "author": _actor_name(c.author) if c.author else "Unknown",
            "createdAt": c.created_at.isoformat() if c.created_at else "",
        })
    return JsonResponse({"ok": True, "comments": data})


@require_POST
@login_required
def api_task_comment_add(request, task_id):
    team, membership = _get_user_team(request.user)
    if not team:
        return JsonResponse({"ok": False, "error": "No team"}, status=400)

    board = _get_team_board(team)
    task = Task.objects.filter(id=task_id, board=board).first()
    if not task:
        return JsonResponse({"ok": False, "error": "Task not found"}, status=404)

    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"ok": False, "error": "Invalid JSON"}, status=400)

    body = (data.get("body") or "").strip()
    if not body:
        return JsonResponse({"ok": False, "error": "Comment body required"}, status=400)

    comment = TaskComment.objects.create(task=task, author=request.user, body=body)

    actor_name = _actor_name(request.user)
    _log_activity(team, request.user, "commented", "task", task.id, task.title,
                  f"{actor_name} commented on '{task.title}'")

    # Parse @mentions and split recipients: mentioned users get a targeted
    # "mention" notification, everyone else gets the generic comment notification.
    mentioned_users = _parse_mentions(body, team)
    mentioned_ids = {u.id for u in mentioned_users if u.id != request.user.id}

    memberships = TeamMembership.objects.filter(team=team).select_related("user")
    notifs = []
    for mship in memberships:
        u = mship.user
        if not u or u.id == request.user.id:
            continue
        if u.id in mentioned_ids:
            notifs.append(Notification(
                team=team, recipient=u, actor=request.user,
                message=f"{actor_name} mentioned you in a comment on '{task.title}'.",
                event_type="task_mention",
                target_tab="tasks", target_type="task", target_id=task.id,
                extra={"taskName": task.title, "commentId": comment.id},
            ))
        else:
            notifs.append(Notification(
                team=team, recipient=u, actor=request.user,
                message=f"{actor_name} commented on task '{task.title}'.",
                event_type="task_comment",
                target_tab="tasks", target_type="task", target_id=task.id,
                extra={"taskName": task.title},
            ))
    if notifs:
        Notification.objects.bulk_create(notifs)

    # Real-time push
    try:
        from core.ws_utils import broadcast_notification
        broadcast_notification(team.id, {
            "message": f"{actor_name} commented on '{task.title}'",
            "event_type": "task_comment",
            "mentionedUserIds": list(mentioned_ids),
        })
    except Exception:
        pass

    mention_emails = [
        (u.email or u.username or "").lower() for u in mentioned_users if u.id != request.user.id
    ]

    return JsonResponse({
        "ok": True,
        "comment": {
            "id": comment.id,
            "body": comment.body,
            "author": actor_name,
            "createdAt": comment.created_at.isoformat(),
            "mentions": mention_emails,
        }
    })


@require_POST
@login_required
def api_task_comment_delete(request, task_id, comment_id):
    team, membership = _get_user_team(request.user)
    if not team:
        return JsonResponse({"ok": False, "error": "No team"}, status=400)

    board = _get_team_board(team)
    task = Task.objects.filter(id=task_id, board=board).first()
    if not task:
        return JsonResponse({"ok": False, "error": "Task not found"}, status=404)

    comment = TaskComment.objects.filter(id=comment_id, task=task).first()
    if comment:
        comment.delete()
    return JsonResponse({"ok": True})


@login_required
def api_task_attachments(request, task_id):
    team, membership = _get_user_team(request.user)
    if not team:
        return JsonResponse({"ok": False, "error": "No team"}, status=400)

    board = _get_team_board(team)
    task = Task.objects.filter(id=task_id, board=board).first()
    if not task:
        return JsonResponse({"ok": False, "error": "Task not found"}, status=404)

    attachments = TaskAttachment.objects.filter(task=task)
    data = []
    for a in attachments:
        data.append({
            "id": a.id,
            "name": a.original_name,
            "size": a.file_size,
            "url": a.file.url if a.file else "",
            "createdAt": a.created_at.isoformat() if a.created_at else "",
        })
    return JsonResponse({"ok": True, "attachments": data})


@require_POST
@login_required
def api_task_attachment_upload(request, task_id):
    team, membership = _get_user_team(request.user)
    if not team:
        return JsonResponse({"ok": False, "error": "No team"}, status=400)

    board = _get_team_board(team)
    task = Task.objects.filter(id=task_id, board=board).first()
    if not task:
        return JsonResponse({"ok": False, "error": "Task not found"}, status=404)

    uploaded = request.FILES.get("file")
    if not uploaded:
        return JsonResponse({"ok": False, "error": "No file"}, status=400)

    err = validate_attachment(uploaded)
    if err:
        return JsonResponse({"ok": False, "error": err}, status=400)

    size_str = ""
    if uploaded.size < 1024:
        size_str = f"{uploaded.size} B"
    elif uploaded.size < 1024 * 1024:
        size_str = f"{uploaded.size / 1024:.1f} KB"
    else:
        size_str = f"{uploaded.size / (1024 * 1024):.1f} MB"

    att = TaskAttachment.objects.create(
        task=task,
        file=uploaded,
        original_name=uploaded.name,
        file_size=size_str,
        uploaded_by=request.user,
    )

    _log_activity(team, request.user, "attached_file", "task", task.id, task.title,
                  f"{_actor_name(request.user)} attached '{uploaded.name}' to '{task.title}'")

    return JsonResponse({
        "ok": True,
        "attachment": {
            "id": att.id,
            "name": att.original_name,
            "size": att.file_size,
            "url": att.file.url if att.file else "",
            "createdAt": att.created_at.isoformat(),
        }
    })


@require_POST
@login_required
def api_task_attachment_delete(request, task_id, attachment_id):
    team, membership = _get_user_team(request.user)
    if not team:
        return JsonResponse({"ok": False, "error": "No team"}, status=400)

    board = _get_team_board(team)
    task = Task.objects.filter(id=task_id, board=board).first()
    if not task:
        return JsonResponse({"ok": False, "error": "Task not found"}, status=404)

    att = TaskAttachment.objects.filter(id=attachment_id, task=task).first()
    if att:
        att.delete()
    return JsonResponse({"ok": True})


@login_required
def api_task_subtasks(request, task_id):
    team, membership = _get_user_team(request.user)
    if not team:
        return JsonResponse({"ok": False, "error": "No team"}, status=400)

    board = _get_team_board(team)
    task = Task.objects.filter(id=task_id, board=board).first()
    if not task:
        return JsonResponse({"ok": False, "error": "Task not found"}, status=404)

    subtasks = Subtask.objects.filter(task=task)
    data = [{
        "id": s.id,
        "title": s.title,
        "isDone": s.is_done,
        "position": s.position,
    } for s in subtasks]
    return JsonResponse({"ok": True, "subtasks": data})


@require_POST
@login_required
def api_task_subtask_save(request, task_id):
    team, membership = _get_user_team(request.user)
    if not team:
        return JsonResponse({"ok": False, "error": "No team"}, status=400)

    board = _get_team_board(team)
    task = Task.objects.filter(id=task_id, board=board).first()
    if not task:
        return JsonResponse({"ok": False, "error": "Task not found"}, status=404)

    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"ok": False, "error": "Invalid JSON"}, status=400)

    subtask_id = data.get("id")
    title = (data.get("title") or "").strip()

    if subtask_id:
        sub = Subtask.objects.filter(id=subtask_id, task=task).first()
        if not sub:
            return JsonResponse({"ok": False, "error": "Subtask not found"}, status=404)
        if title:
            sub.title = title
        if "isDone" in data:
            sub.is_done = bool(data["isDone"])
        sub.save()
    else:
        if not title:
            return JsonResponse({"ok": False, "error": "Title required"}, status=400)
        max_pos = Subtask.objects.filter(task=task).count()
        sub = Subtask.objects.create(task=task, title=title, position=max_pos)

    return JsonResponse({
        "ok": True,
        "subtask": {
            "id": sub.id,
            "title": sub.title,
            "isDone": sub.is_done,
            "position": sub.position,
        }
    })


@require_POST
@login_required
def api_task_subtask_delete(request, task_id, subtask_id):
    team, membership = _get_user_team(request.user)
    if not team:
        return JsonResponse({"ok": False, "error": "No team"}, status=400)

    board = _get_team_board(team)
    task = Task.objects.filter(id=task_id, board=board).first()
    if not task:
        return JsonResponse({"ok": False, "error": "Task not found"}, status=404)

    sub = Subtask.objects.filter(id=subtask_id, task=task).first()
    if sub:
        sub.delete()
    return JsonResponse({"ok": True})


