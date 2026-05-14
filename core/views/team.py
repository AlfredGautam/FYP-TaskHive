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
    _actor_name, _notify_team, _get_team_board, _log_activity,
)

logger = logging.getLogger(__name__)


def _gen_team_code() -> str:
    return "TEAM-" + secrets.token_hex(4).upper()


def _bootstrap_team_workspace(team: Team, actor: User) -> Workspace:
    workspace = Workspace.objects.create(team=team, name=f"{team.name} Workspace", created_by=actor)
    board = Board.objects.create(workspace=workspace, name="Main Board", created_by=actor)
    Column.objects.create(board=board, name="To Do", position=1)
    Column.objects.create(board=board, name="In Progress", position=2)
    Column.objects.create(board=board, name="Done", position=3)
    return workspace


@require_POST
@login_required
def api_team_create(request):
    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"ok": False, "error": "Invalid JSON"}, status=400)

    name = (data.get("name") or "").strip()
    if not name:
        return JsonResponse({"ok": False, "error": "Team name required"}, status=400)

    code = _gen_team_code()
    attempts = 0
    while Team.objects.filter(code=code).exists() and attempts < 10:
        code = _gen_team_code()
        attempts += 1
    if Team.objects.filter(code=code).exists():
        return JsonResponse({"ok": False, "error": "Failed generating team code"}, status=500)

    team = Team.objects.create(name=name, code=code, created_by=request.user)
    TeamMembership.objects.create(team=team, user=request.user, role=TeamMembership.ROLE_HEAD)

    _bootstrap_team_workspace(team=team, actor=request.user)

    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    profile.current_team = team
    profile.save(update_fields=["current_team"])

    return JsonResponse({
        "ok": True,
        "team": {"id": team.id, "name": team.name, "code": team.code},
        "role": TeamMembership.ROLE_HEAD,
        "redirect": f"/workspace/{team.id}/",
    })


@require_POST
@login_required
def api_team_invite(request):
    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"ok": False, "error": "Invalid JSON"}, status=400)

    team_id = data.get("team_id")
    identifier = (data.get("email") or data.get("username") or "").strip().lower()
    if not team_id or not identifier:
        return JsonResponse({"ok": False, "error": "team_id and email required"}, status=400)

    membership = TeamMembership.objects.filter(team_id=team_id, user=request.user).first()
    if not membership:
        return JsonResponse({"ok": False, "error": "Not a team member"}, status=403)
    if membership.role != TeamMembership.ROLE_HEAD:
        return JsonResponse({"ok": False, "error": "Only admin can invite members"}, status=403)

    team = Team.objects.filter(id=team_id).first()
    if not team:
        return JsonResponse({"ok": False, "error": "Team not found"}, status=404)

    invited_user = User.objects.filter(username=identifier).first()
    if not invited_user:
        invited_user = User.objects.filter(email__iexact=identifier).first()
    if not invited_user:
        return JsonResponse({"ok": False, "error": "User not found. Ask them to register first."}, status=404)

    # Already a member?
    if TeamMembership.objects.filter(team=team, user=invited_user).exists():
        return JsonResponse({"ok": True, "created": False, "message": "User is already in the team."})

    # Already has a pending invite?
    if TeamInvitation.objects.filter(team=team, invited_user=invited_user, status=TeamInvitation.STATUS_PENDING).exists():
        return JsonResponse({"ok": True, "created": False, "message": "Invitation already pending."})

    # Create pending invitation
    invitation = TeamInvitation.objects.create(
        team=team,
        invited_by=request.user,
        invited_user=invited_user,
    )

    # Send personal notification to invited user (not the whole team)
    Notification.objects.create(
        team=team,
        recipient=invited_user,
        actor=request.user,
        message=f"{_actor_name(request.user)} invited you to join team '{team.name}'.",
        event_type="team_invitation",
        target_tab="team",
        target_type="invitation",
        target_id=invitation.id,
        extra={"teamId": team.id, "invitationId": invitation.id},
    )

    # Real-time push to the invited user's personal WebSocket room
    from core.ws_utils import broadcast_to_user
    broadcast_to_user(invited_user.id, {"message": "New invitation", "event_type": "team_invitation"})

    # Send invitation email via Gmail
    from .email_utils import _site_url
    site = _site_url()
    accept_url = f"{site}/invite/{invitation.token}/accept/"
    decline_url = f"{site}/invite/{invitation.token}/decline/"
    send_team_invitation_email(
        invitee_name=invited_user.get_full_name() or invited_user.username,
        invitee_email=invited_user.email,
        team_name=team.name,
        invited_by_name=_actor_name(request.user),
        accept_url=accept_url,
        decline_url=decline_url,
    )

    return JsonResponse({
        "ok": True,
        "created": True,
        "message": "Invitation sent! Waiting for user to accept.",
    })


@login_required
def api_my_invitations(request):
    """List pending invitations for the current user."""
    invitations = TeamInvitation.objects.filter(
        invited_user=request.user,
        status=TeamInvitation.STATUS_PENDING,
    ).select_related("team", "invited_by")

    result = []
    for inv in invitations:
        result.append({
            "id": inv.id,
            "teamName": inv.team.name,
            "teamId": inv.team.id,
            "invitedBy": inv.invited_by.get_full_name() or inv.invited_by.username,
            "createdAt": inv.created_at.isoformat(),
        })

    return JsonResponse({"ok": True, "invitations": result})


@login_required
def api_team_pending_invitations(request, team_id):
    """Admin view — list all invitations (pending/accepted/declined) for a team."""
    membership = TeamMembership.objects.filter(team_id=team_id, user=request.user).first()
    if not membership or membership.role != TeamMembership.ROLE_HEAD:
        return JsonResponse({"ok": False, "error": "Only admin can view invitations"}, status=403)

    invitations = TeamInvitation.objects.filter(team_id=team_id).select_related("invited_user", "invited_user__profile", "invited_by").order_by("-created_at")[:50]

    def _photo(u):
        prof = getattr(u, "profile", None)
        if prof and prof.photo:
            try: return prof.photo.url
            except Exception: return ""
        return ""

    result = []
    for inv in invitations:
        result.append({
            "id": inv.id,
            "invitedUser": inv.invited_user.get_full_name() or inv.invited_user.username,
            "invitedEmail": inv.invited_user.email or inv.invited_user.username,
            "invitedUserPhoto": _photo(inv.invited_user),
            "invitedBy": inv.invited_by.get_full_name() or inv.invited_by.username,
            "status": inv.status,
            "createdAt": inv.created_at.isoformat(),
            "respondedAt": inv.responded_at.isoformat() if inv.responded_at else None,
        })
    return JsonResponse({"ok": True, "invitations": result})


@require_POST
@login_required
def api_invitation_resend(request):
    """Admin re-sends the invitation email for a pending invitation."""
    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"ok": False, "error": "Invalid JSON"}, status=400)

    invitation_id = data.get("invitation_id")
    if not invitation_id:
        return JsonResponse({"ok": False, "error": "invitation_id required"}, status=400)

    invitation = TeamInvitation.objects.filter(id=invitation_id, status=TeamInvitation.STATUS_PENDING).select_related("team", "invited_user", "invited_by").first()
    if not invitation:
        return JsonResponse({"ok": False, "error": "Pending invitation not found"}, status=404)

    # Only admin of the team can re-send
    membership = TeamMembership.objects.filter(team=invitation.team, user=request.user, role=TeamMembership.ROLE_HEAD).first()
    if not membership:
        return JsonResponse({"ok": False, "error": "Only admin can resend invitations"}, status=403)

    from .email_utils import _site_url
    site = _site_url()
    accept_url = f"{site}/invite/{invitation.token}/accept/"
    decline_url = f"{site}/invite/{invitation.token}/decline/"
    send_team_invitation_email(
        invitee_name=invitation.invited_user.get_full_name() or invitation.invited_user.username,
        invitee_email=invitation.invited_user.email,
        team_name=invitation.team.name,
        invited_by_name=_actor_name(request.user),
        accept_url=accept_url,
        decline_url=decline_url,
    )

    # Also re-push via WebSocket
    from core.ws_utils import broadcast_to_user
    broadcast_to_user(invitation.invited_user.id, {"message": "Invitation re-sent", "event_type": "team_invitation"})

    return JsonResponse({"ok": True, "message": "Invitation email re-sent."})


@require_POST
@login_required
def api_invitation_respond(request):
    """Accept or decline a team invitation."""
    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"ok": False, "error": "Invalid JSON"}, status=400)

    invitation_id = data.get("invitation_id")
    action = data.get("action")  # "accept" or "decline"

    if not invitation_id or action not in ("accept", "decline"):
        return JsonResponse({"ok": False, "error": "invitation_id and action (accept/decline) required"}, status=400)

    invitation = TeamInvitation.objects.filter(
        id=invitation_id,
        invited_user=request.user,
        status=TeamInvitation.STATUS_PENDING,
    ).select_related("team").first()

    if not invitation:
        return JsonResponse({"ok": False, "error": "Invitation not found or already responded"}, status=404)

    invitation.responded_at = timezone.now()

    if action == "accept":
        invitation.status = TeamInvitation.STATUS_ACCEPTED
        invitation.save(update_fields=["status", "responded_at"])

        # Create team membership
        membership, created = TeamMembership.objects.get_or_create(
            team=invitation.team, user=request.user
        )
        if created:
            membership.role = TeamMembership.ROLE_MEMBER
            membership.save(update_fields=["role"])

        _notify_team(
            invitation.team,
            request.user,
            f"{_actor_name(request.user)} accepted the invitation and joined team '{invitation.team.name}'.",
            event_type="team_member_added",
            target_tab="team",
            target_type="member",
            target_id=request.user.id,
        )

        return JsonResponse({"ok": True, "status": "accepted", "teamName": invitation.team.name})

    else:
        invitation.status = TeamInvitation.STATUS_DECLINED
        invitation.save(update_fields=["status", "responded_at"])

        # Notify the team admin who sent the invite
        Notification.objects.create(
            team=invitation.team,
            recipient=invitation.invited_by,
            actor=request.user,
            message=f"{_actor_name(request.user)} declined the invitation to join team '{invitation.team.name}'.",
            event_type="team_invitation_declined",
            target_tab="team",
            target_type="invitation",
            target_id=invitation.id,
        )
        from core.ws_utils import broadcast_notification
        broadcast_notification(invitation.team.id, {"event_type": "team_invitation_declined"})

        return JsonResponse({"ok": True, "status": "declined"})


@login_required
def invitation_accept_token(request, token):
    """Handle email Accept link — GET shows confirmation page, POST accepts."""
    invitation = TeamInvitation.objects.filter(
        token=token, invited_user=request.user,
    ).select_related("team", "invited_by").first()

    ctx = {"token": token}

    if not invitation:
        ctx.update(error_title="Not Found", error="This invitation link is invalid or was not sent to your account.")
        return render(request, "core/invitation_respond.html", ctx)

    if invitation.status != TeamInvitation.STATUS_PENDING:
        ctx.update(error_title="Already Responded", error=f"This invitation was already {invitation.status}.")
        return render(request, "core/invitation_respond.html", ctx)

    if request.method == "GET":
        ctx.update(team_name=invitation.team.name, invited_by=_actor_name(invitation.invited_by))
        return render(request, "core/invitation_respond.html", ctx)

    # POST — accept
    invitation.status = TeamInvitation.STATUS_ACCEPTED
    invitation.responded_at = timezone.now()
    invitation.save(update_fields=["status", "responded_at"])

    membership, created = TeamMembership.objects.get_or_create(team=invitation.team, user=request.user)
    if created:
        membership.role = TeamMembership.ROLE_MEMBER
        membership.save(update_fields=["role"])

    # Set current team for the user
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    profile.current_team_id = invitation.team.id
    profile.save(update_fields=["current_team_id"])

    _notify_team(
        invitation.team, request.user,
        f"{_actor_name(request.user)} accepted the invitation and joined team '{invitation.team.name}'.",
        event_type="team_member_added", target_tab="team", target_type="member", target_id=request.user.id,
    )

    ctx.update(status="accepted", team_name=invitation.team.name)
    return render(request, "core/invitation_respond.html", ctx)


@login_required
def invitation_decline_token(request, token):
    """Handle email Decline link — GET shows confirmation page, POST declines."""
    invitation = TeamInvitation.objects.filter(
        token=token, invited_user=request.user,
    ).select_related("team", "invited_by").first()

    ctx = {"token": token}

    if not invitation:
        ctx.update(error_title="Not Found", error="This invitation link is invalid or was not sent to your account.")
        return render(request, "core/invitation_respond.html", ctx)

    if invitation.status != TeamInvitation.STATUS_PENDING:
        ctx.update(error_title="Already Responded", error=f"This invitation was already {invitation.status}.")
        return render(request, "core/invitation_respond.html", ctx)

    if request.method == "GET":
        ctx.update(team_name=invitation.team.name, invited_by=_actor_name(invitation.invited_by))
        return render(request, "core/invitation_respond.html", ctx)

    # POST — decline
    invitation.status = TeamInvitation.STATUS_DECLINED
    invitation.responded_at = timezone.now()
    invitation.save(update_fields=["status", "responded_at"])

    Notification.objects.create(
        team=invitation.team, recipient=invitation.invited_by, actor=request.user,
        message=f"{_actor_name(request.user)} declined the invitation to join team '{invitation.team.name}'.",
        event_type="team_invitation_declined", target_tab="team", target_type="invitation", target_id=invitation.id,
    )
    from core.ws_utils import broadcast_notification, broadcast_to_user
    broadcast_notification(invitation.team.id, {"event_type": "team_invitation_declined"})
    broadcast_to_user(invitation.invited_by.id, {"event_type": "team_invitation_declined"})

    ctx.update(status="declined", team_name=invitation.team.name)
    return render(request, "core/invitation_respond.html", ctx)


@require_POST
@login_required
def api_team_join(request):
    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"ok": False, "error": "Invalid JSON"}, status=400)

    code = (data.get("code") or "").strip().upper()
    if not code:
        return JsonResponse({"ok": False, "error": "Team code required"}, status=400)

    team = Team.objects.filter(code=code).first()
    if not team:
        return JsonResponse({"ok": False, "error": "Invalid team code"}, status=404)

    membership, created = TeamMembership.objects.get_or_create(team=team, user=request.user)
    if created:
        membership.role = TeamMembership.ROLE_MEMBER
        membership.save(update_fields=["role"])
        _notify_team(
            team,
            request.user,
            f"{_actor_name(request.user)} joined team {team.name}.",
            event_type="team_member_joined",
            target_tab="team",
            target_type="member",
            target_id=request.user.id,
            extra={"teamId": team.id},
        )

    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    profile.current_team = team
    profile.save(update_fields=["current_team"])

    return JsonResponse({
        "ok": True,
        "team": {"id": team.id, "name": team.name, "code": team.code},
        "role": membership.role,
        "redirect": f"/workspace/{team.id}/",
    })


@login_required
def api_my_teams(request):
    memberships = (
        TeamMembership.objects
        .select_related("team")
        .filter(user=request.user)
        .order_by("-joined_at")
    )
    teams = []
    for m in memberships:
        teams.append({
            "id": m.team.id,
            "name": m.team.name,
            "code": m.team.code,
            "role": m.role,
            "is_owner": (m.user_id == m.team.created_by_id),
            "joined_at": m.joined_at.isoformat(),
        })
    return JsonResponse({"ok": True, "teams": teams})


@login_required
def api_team_current(request):
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if not profile.current_team_id:
        return JsonResponse({"ok": True, "team": None})

    team = Team.objects.filter(id=profile.current_team_id).first()
    if not team:
        profile.current_team = None
        profile.save(update_fields=["current_team"])
        return JsonResponse({"ok": True, "team": None})

    membership = TeamMembership.objects.filter(team=team, user=request.user).first()
    role = membership.role if membership else TeamMembership.ROLE_MEMBER
    return JsonResponse({
        "ok": True,
        "team": {"id": team.id, "name": team.name, "code": team.code},
        "role": role,
    })


@login_required
def api_team_members(request, team_id: int):
    is_member = TeamMembership.objects.filter(team_id=team_id, user=request.user).exists()
    if not is_member:
        return JsonResponse({"ok": False, "error": "Not a team member"}, status=403)

    team_obj = Team.objects.filter(id=team_id).first()
    owner_id = team_obj.created_by_id if team_obj else None

    memberships = (
        TeamMembership.objects
        .select_related("user", "user__profile")
        .filter(team_id=team_id)
        .order_by("role", "joined_at")
    )

    def _photo(u):
        prof = getattr(u, "profile", None)
        if prof and prof.photo:
            try: return prof.photo.url
            except Exception: return ""
        return ""

    return JsonResponse({
        "ok": True,
        "members": [
            {
                "email": (m.user.email or m.user.username),
                "name": (m.user.get_full_name() or m.user.username),
                "username": m.user.username,
                "role": m.role,
                "is_owner": (m.user_id == owner_id),
                "photo_url": _photo(m.user),
            }
            for m in memberships
        ],
    })


@require_POST
@login_required
def api_team_delete(request):
    """Delete a team entirely. Only the team owner (head) can do this."""
    try:
        data = json.loads(request.body)
    except Exception:
        return JsonResponse({"ok": False, "error": "Invalid JSON"}, status=400)

    team_id = data.get("team_id")
    if not team_id:
        return JsonResponse({"ok": False, "error": "team_id required"}, status=400)

    team = Team.objects.filter(id=team_id).first()
    if not team:
        return JsonResponse({"ok": False, "error": "Team not found"}, status=404)

    membership = TeamMembership.objects.filter(team=team, user=request.user).first()
    if not membership or membership.role != TeamMembership.ROLE_HEAD:
        return JsonResponse({"ok": False, "error": "Only the team owner can delete the team"}, status=403)

    # Clear current_team for all members
    member_ids = list(TeamMembership.objects.filter(team=team).values_list("user_id", flat=True))
    UserProfile.objects.filter(user_id__in=member_ids, current_team=team).update(current_team=None)

    # Delete the team (cascades to memberships, workspaces, boards, tasks, etc.)
    team.delete()

    return JsonResponse({"ok": True, "redirect": "/user/"})


@require_POST
@login_required
def api_team_leave(request):
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if not profile.current_team_id:
        return JsonResponse({"ok": True})

    team_id = profile.current_team_id
    team_obj = Team.objects.filter(id=team_id).first()

    TeamMembership.objects.filter(team_id=team_id, user=request.user).delete()

    profile.current_team = None
    profile.save(update_fields=["current_team"])

    # Clean up leftover references to this user inside the team's tasks and projects
    if team_obj:
        board = _get_team_board(team_obj)
        if board:
            for task in Task.objects.filter(board=board).prefetch_related("assignees"):
                task.assignees.remove(request.user)

        user_email = (request.user.email or request.user.username or "").lower()
        for project in Project.objects.filter(team_id=team_id):
            members = project.members if isinstance(project.members, list) else []
            cleaned = [m for m in members if (m or "").lower() != user_email]
            if cleaned != members:
                project.members = cleaned
                project.save(update_fields=["members"])

    # Wipe this user's notifications for this team so a rejoin starts clean
    Notification.objects.filter(team_id=team_id, recipient=request.user).delete()

    if not TeamMembership.objects.filter(team_id=team_id).exists():
        Team.objects.filter(id=team_id).delete()

    return JsonResponse({"ok": True, "redirect": "/user/"})


@require_POST
@login_required
def api_team_member_remove(request):
    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"ok": False, "error": "Invalid JSON"}, status=400)

    team_id = data.get("team_id")
    member_email = (data.get("member_email") or "").strip().lower()
    if not team_id or not member_email:
        return JsonResponse({"ok": False, "error": "team_id and member_email required"}, status=400)

    admin_membership = TeamMembership.objects.filter(team_id=team_id, user=request.user).first()
    if not admin_membership:
        return JsonResponse({"ok": False, "error": "Not a team member"}, status=403)
    if admin_membership.role != TeamMembership.ROLE_HEAD:
        return JsonResponse({"ok": False, "error": "Only admin can remove members"}, status=403)

    target_user = User.objects.filter(email__iexact=member_email).first()
    if not target_user:
        return JsonResponse({"ok": False, "error": "User not found"}, status=404)
    if target_user.id == request.user.id:
        return JsonResponse({"ok": False, "error": "Use leave team to remove yourself"}, status=400)

    target_membership = TeamMembership.objects.filter(team_id=team_id, user=target_user).first()
    if not target_membership:
        return JsonResponse({"ok": False, "error": "User is not in this team"}, status=404)

    team_obj = Team.objects.filter(id=team_id).first()
    owner_id = team_obj.created_by_id if team_obj else None
    if target_user.id == owner_id:
        return JsonResponse({"ok": False, "error": "The team owner cannot be removed"}, status=403)
    if target_membership.role == TeamMembership.ROLE_HEAD and request.user.id != owner_id:
        return JsonResponse({"ok": False, "error": "Only the team owner can remove admins"}, status=403)

    target_membership.delete()

    UserProfile.objects.filter(user=target_user, current_team_id=team_id).update(current_team=None)

    board = _get_team_board(admin_membership.team)
    for task in Task.objects.filter(board=board).prefetch_related("assignees"):
        task.assignees.remove(target_user)

    target_email = (target_user.email or target_user.username or "").lower()
    for project in Project.objects.filter(team_id=team_id):
        members = project.members if isinstance(project.members, list) else []
        cleaned = [m for m in members if (m or "").lower() != target_email]
        if cleaned != members:
            project.members = cleaned
            project.save(update_fields=["members"])

    # Wipe the removed user's notifications for this team so a rejoin starts clean
    Notification.objects.filter(team_id=team_id, recipient=target_user).delete()

    _notify_team(
        admin_membership.team,
        request.user,
        f"{_actor_name(request.user)} removed {target_user.get_full_name() or target_user.username} from team {admin_membership.team.name}.",
        event_type="team_member_removed",
        target_tab="team",
        target_type="member",
        target_id=target_user.id,
        extra={"teamId": admin_membership.team_id, "memberEmail": target_email},
    )

    return JsonResponse({"ok": True})


@require_POST
@login_required
def api_team_member_promote(request):
    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"ok": False, "error": "Invalid JSON"}, status=400)

    team_id = data.get("team_id")
    member_email = (data.get("member_email") or "").strip().lower()
    if not team_id or not member_email:
        return JsonResponse({"ok": False, "error": "team_id and member_email required"}, status=400)

    admin_membership = TeamMembership.objects.filter(team_id=team_id, user=request.user).first()
    if not admin_membership:
        return JsonResponse({"ok": False, "error": "Not a team member"}, status=403)
    if admin_membership.role != TeamMembership.ROLE_HEAD:
        return JsonResponse({"ok": False, "error": "Only admin can promote members"}, status=403)

    from django.db.models import Q
    target_membership = (
        TeamMembership.objects
        .select_related("user")
        .filter(team_id=team_id)
        .filter(Q(user__email__iexact=member_email) | Q(user__username__iexact=member_email))
        .first()
    )
    if not target_membership:
        return JsonResponse({"ok": False, "error": "User is not in this team"}, status=404)

    target_user = target_membership.user
    if target_user.id == request.user.id:
        return JsonResponse({"ok": False, "error": "You are already an admin"}, status=400)
    if target_membership.role == TeamMembership.ROLE_HEAD:
        return JsonResponse({"ok": False, "error": "User is already an admin"}, status=400)

    target_membership.role = TeamMembership.ROLE_HEAD
    target_membership.save(update_fields=["role"])

    _notify_team(
        admin_membership.team,
        request.user,
        f"{_actor_name(request.user)} promoted {target_user.get_full_name() or target_user.username} to admin.",
        event_type="team_member_promoted",
        target_tab="team",
        target_type="member",
        target_id=target_user.id,
        extra={"teamId": admin_membership.team_id},
    )

    return JsonResponse({"ok": True})


@require_POST
@login_required
def api_team_member_demote(request):
    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"ok": False, "error": "Invalid JSON"}, status=400)

    team_id = data.get("team_id")
    member_email = (data.get("member_email") or "").strip().lower()
    if not team_id or not member_email:
        return JsonResponse({"ok": False, "error": "team_id and member_email required"}, status=400)

    admin_membership = TeamMembership.objects.filter(team_id=team_id, user=request.user).first()
    if not admin_membership:
        return JsonResponse({"ok": False, "error": "Not a team member"}, status=403)
    if admin_membership.role != TeamMembership.ROLE_HEAD:
        return JsonResponse({"ok": False, "error": "Only admin can demote members"}, status=403)

    from django.db.models import Q
    target_membership = (
        TeamMembership.objects
        .select_related("user")
        .filter(team_id=team_id)
        .filter(Q(user__email__iexact=member_email) | Q(user__username__iexact=member_email))
        .first()
    )
    if not target_membership:
        return JsonResponse({"ok": False, "error": "User is not in this team"}, status=404)

    target_user = target_membership.user
    if target_user.id == request.user.id:
        return JsonResponse({"ok": False, "error": "You cannot demote yourself"}, status=400)

    team_obj = Team.objects.filter(id=team_id).first()
    if team_obj and target_user.id == team_obj.created_by_id:
        return JsonResponse({"ok": False, "error": "The team owner cannot be demoted"}, status=403)

    if target_membership.role == TeamMembership.ROLE_MEMBER:
        return JsonResponse({"ok": False, "error": "User is already a member"}, status=400)

    target_membership.role = TeamMembership.ROLE_MEMBER
    target_membership.save(update_fields=["role"])

    _notify_team(
        admin_membership.team,
        request.user,
        f"{_actor_name(request.user)} demoted {target_user.get_full_name() or target_user.username} to member.",
        event_type="team_member_demoted",
        target_tab="team",
        target_type="member",
        target_id=target_user.id,
        extra={"teamId": admin_membership.team_id},
    )

    return JsonResponse({"ok": True})


