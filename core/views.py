

import json
import logging
import random
import secrets
from datetime import timedelta, date

logger = logging.getLogger(__name__)

from django.conf import settings
from django.core.mail import send_mail
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.hashers import make_password, check_password
from django.contrib.auth.models import User
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import (
    CodeFile,
    PasswordOTP,
    EmailVerificationOTP,
    UserProfile,
    Team,
    TeamMembership,
    TeamInvitation,
    Workspace,
    Board,
    Column,
    Task,
    Project,
    ProjectFile,
    ApprovalRequest,
    Notification,
    ActivityLog,
    Subtask,
    TaskAttachment,
    TaskComment,
)
from .email_utils import (
    send_welcome_email,
    send_task_assigned_email,
    send_deadline_reminder_email,
    send_team_invitation_email,
)
from .rate_limit import rate_limit


def error_404(request, exception=None):
    return render(request, "404.html", status=404)


def error_500(request):
    return render(request, "500.html", status=500)


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


# =========================
# PAGES
# =========================

def dashboard_page(request):
    return render(request, "core/dashboard.html")


@ensure_csrf_cookie
def login_page(request):
    return render(request, "core/login_new.html")


@login_required
def user_page(request):
    return render(request, "core/user.html")


@login_required
def workspace(request):
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if not profile.current_team_id:
        return render(request, "core/user.html")
    return render(request, "core/index.html")


@login_required
def workspace_team(request, team_id: int):
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
    return render(request, "core/analytics.html")


@ensure_csrf_cookie
@login_required
def codespace_page(request):
    return render(request, "core/codespace.html")


@login_required
def profile_page(request):
    return render(request, "core/profile.html")


@login_required
def public_profile_page(request, username: str):
    return render(request, "core/public_profile.html", {"profile_username": username})


# =========================
# AUTH APIs
# =========================

@login_required
def api_me(request):
    """
    ✅ Single source of truth (fixed)
    Returns user + profile data
    """
    u = request.user
    profile, _ = UserProfile.objects.get_or_create(user=u)

    return JsonResponse({
        "ok": True,
        "user": {
            "name": (u.first_name or u.username),
            "email": (u.email or u.username),
            "username": u.username,

            # profile extras
            "displayName": profile.display_name,
            "profileUsername": profile.username_public,
            "tagline": profile.tagline,
            "bio": profile.bio,
            "github": profile.github,
            "linkedin": profile.linkedin,
            "themeMode": profile.theme_mode,
            "accentColor": profile.accent_color,
            "photoUrl": profile.photo.url if profile.photo else "",
            "coverUrl": profile.cover_photo.url if profile.cover_photo else "",
        }
    })


@csrf_exempt
@require_POST
@rate_limit(max_requests=10, window_seconds=60)
def api_login(request):
    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"ok": False, "error": "Invalid JSON"}, status=400)

    email = (data.get("email") or data.get("username") or "").strip().lower()
    password = data.get("password") or ""

    if not email or not password:
        return JsonResponse({"ok": False, "error": "Email and password required"}, status=400)

    user = authenticate(request, username=email, password=password)
    if user is None:
        # Check if user exists but password is wrong or unset (e.g. Google-only account)
        from django.contrib.auth.models import User as _U
        existing = _U.objects.filter(username=email).first() or _U.objects.filter(email__iexact=email).first()
        if existing and not existing.has_usable_password():
            return JsonResponse({"ok": False, "error": "This account has no password set. Please use 'Forgot password?' to create one."}, status=401)
        return JsonResponse({"ok": False, "error": "Invalid email or password."}, status=401)

    login(request, user)
    return JsonResponse({"ok": True, "redirect": "/user/"})


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
def api_team_leave(request):
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if not profile.current_team_id:
        return JsonResponse({"ok": True})

    team_id = profile.current_team_id
    TeamMembership.objects.filter(team_id=team_id, user=request.user).delete()

    profile.current_team = None
    profile.save(update_fields=["current_team"])

    if not TeamMembership.objects.filter(team_id=team_id).exists():
        Team.objects.filter(id=team_id).delete()

    return JsonResponse({"ok": True, "redirect": "/user/"})


@csrf_exempt
@require_POST
@rate_limit(max_requests=5, window_seconds=60)
def api_register(request):
    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"ok": False, "error": "Invalid JSON"}, status=400)

    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    if not name or not email or not password:
        return JsonResponse({"ok": False, "error": "Name, email, password required"}, status=400)

    if len(password) < 6:
        return JsonResponse({"ok": False, "error": "Password must be at least 6 characters"}, status=400)

    if User.objects.filter(username=email).exists():
        return JsonResponse({"ok": False, "error": "User already exists"}, status=409)

    code = _gen_verification_code()
    expires = timezone.now() + timedelta(minutes=10)

    EmailVerificationOTP.objects.filter(email=email, used=False).update(used=True)
    EmailVerificationOTP.objects.create(
        name=name,
        email=email,
        password_hash=make_password(password),
        otp_hash=make_password(code),
        expires_at=expires,
        used=False,
    )

    try:
        _send_email_verification_code(email=email, name=name, code=code)
    except Exception as e:
        return JsonResponse({"ok": False, "error": f"Failed to send verification code: {str(e)}"}, status=500)

    return JsonResponse({
        "ok": True,
        "verificationRequired": True,
        "message": "Verification code sent to your email.",
    })


@csrf_exempt
@require_POST
def api_register_verify(request):
    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"ok": False, "error": "Invalid JSON"}, status=400)

    email = (data.get("email") or "").strip().lower()
    code = (data.get("code") or "").strip()

    if not email or not code:
        return JsonResponse({"ok": False, "error": "email and code required"}, status=400)

    record = EmailVerificationOTP.objects.filter(email=email, used=False).order_by("-created_at").first()
    if not record:
        return JsonResponse({"ok": False, "error": "Verification session not found. Register again."}, status=404)

    if timezone.now() > record.expires_at:
        record.used = True
        record.save(update_fields=["used"])
        return JsonResponse({"ok": False, "error": "Verification code expired. Please register again."}, status=400)

    if not check_password(code, record.otp_hash):
        return JsonResponse({"ok": False, "error": "Invalid verification code."}, status=400)

    if User.objects.filter(username=email).exists():
        record.used = True
        record.save(update_fields=["used"])
        return JsonResponse({"ok": False, "error": "User already exists"}, status=409)

    user = User(username=email, email=email, first_name=record.name)
    user.password = record.password_hash
    user.save()

    record.used = True
    record.save(update_fields=["used"])

    send_welcome_email(user_name=(record.name or email.split("@")[0]), user_email=email)

    login(request, user)
    return JsonResponse({"ok": True, "redirect": "/user/"})


@require_POST
def api_logout(request):
    logout(request)
    return JsonResponse({"ok": True})


# =========================
# CODESPACE APIs (DB based)
# =========================

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


# ✅ THIS IS WHAT YOU NEED FOR "NEW FILE" BUTTON
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


# =========================
# FORGOT PASSWORD (OTP)
# =========================

def _gen_otp():
    return f"{random.randint(0, 999999):06d}"


def _gen_verification_code():
    return f"{random.randint(0, 999999):06d}"


def _send_email_verification_code(email: str, name: str, code: str):
    subject = "TaskHive Email Verification Code"
    message = (
        f"Hi {name},\n\n"
        f"Your TaskHive email verification code is: {code}\n\n"
        "This code expires in 10 minutes.\n"
        "If you did not request this, you can ignore this email.\n\n"
        "- TaskHive"
    )
    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", None) or getattr(settings, "EMAIL_HOST_USER", None)
    send_mail(subject, message, from_email, [email], fail_silently=False)


@csrf_exempt
@require_POST
@rate_limit(max_requests=3, window_seconds=60)
def api_password_request_otp(request):
    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"ok": False, "error": "Invalid JSON"}, status=400)

    email = (data.get("email") or "").strip().lower()
    if not email:
        return JsonResponse({"ok": False, "error": "Email required"}, status=400)

    if not User.objects.filter(username=email).exists():
        return JsonResponse({"ok": False, "error": "No account found with this email."}, status=404)

    otp = _gen_otp()
    expires = timezone.now() + timedelta(minutes=10)

    PasswordOTP.objects.filter(email=email, used=False).update(used=True)

    PasswordOTP.objects.create(
        email=email,
        otp_hash=make_password(otp),
        expires_at=expires,
        used=False,
    )

    subject = "TaskHive Password Reset OTP"
    message = (
        f"Your TaskHive OTP is: {otp}\n\n"
        f"Expires in 10 minutes.\n"
        f"If you didn’t request this, ignore."
    )

    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", None) or getattr(settings, "EMAIL_HOST_USER", None)

    try:
        send_mail(subject, message, from_email, [email], fail_silently=False)
    except Exception as e:
        return JsonResponse({"ok": False, "error": f"Email send failed: {str(e)}"}, status=500)

    return JsonResponse({"ok": True})


@csrf_exempt
@require_POST
@rate_limit(max_requests=5, window_seconds=60)
def api_password_reset(request):
    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"ok": False, "error": "Invalid JSON"}, status=400)

    email = (data.get("email") or "").strip().lower()
    otp = (data.get("otp") or "").strip()
    new_password = data.get("new_password") or ""

    if not email or not otp or not new_password:
        return JsonResponse({"ok": False, "error": "email, otp, new_password required"}, status=400)

    if len(new_password) < 6:
        return JsonResponse({"ok": False, "error": "Password must be at least 6 characters"}, status=400)

    record = PasswordOTP.objects.filter(email=email, used=False).order_by("-created_at").first()
    if not record:
        return JsonResponse({"ok": False, "error": "OTP not found. Request a new OTP."}, status=400)

    if timezone.now() > record.expires_at:
        record.used = True
        record.save(update_fields=["used"])
        return JsonResponse({"ok": False, "error": "OTP expired. Request a new OTP."}, status=400)

    if not check_password(otp, record.otp_hash):
        return JsonResponse({"ok": False, "error": "Invalid OTP."}, status=400)

    try:
        user = User.objects.get(username=email)
    except User.DoesNotExist:
        return JsonResponse({"ok": False, "error": "User not found."}, status=404)

    try:
        user.set_password(new_password)
        user.save()
    except Exception as e:
        return JsonResponse({"ok": False, "error": f"Password update failed: {str(e)}"}, status=500)

    record.used = True
    record.save(update_fields=["used"])

    return JsonResponse({"ok": True})


# =========================
# PROFILE APIs
# =========================

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
        },
    })


# =========================
# HELPER: get current team for user
# =========================

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
    }


# =========================
# WORKSPACE DATA APIs
# =========================

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

    tasks_qs = Task.objects.filter(board=board).select_related("column").prefetch_related("assignees")
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
    name = (data.get("name") or "").strip()
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
    project_id = data.get("projectId")
    if project_id is not None:
        code_meta["_projectId"] = project_id

    is_update = bool(task_id)
    old_assignee_ids = set()
    if task_id:
        try:
            task = Task.objects.get(id=task_id, board=board)
        except Task.DoesNotExist:
            return JsonResponse({"ok": False, "error": "Task not found"}, status=404)
        # Capture old state before any modification
        old_assignee_ids = set(task.assignees.values_list("id", flat=True))
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

    task.assignees.clear()
    assignees = data.get("assignees", [])
    new_assignee_users = []
    if assignees:
        new_assignee_users = list(User.objects.filter(
            id__in=TeamMembership.objects.filter(
                team=team,
                user__email__in=assignees,
            ).values_list("user_id", flat=True)
        ))
        task.assignees.set(new_assignee_users)

    # Determine which assignees are truly new (not previously assigned)
    truly_new_assignee_users = [u for u in new_assignee_users if u.id not in old_assignee_ids]

    _notify_team(
        team,
        request.user,
        f"{_actor_name(request.user)} {'updated' if is_update else 'created'} task '{task.title}'.",
        event_type="task_updated" if is_update else "task_created",
        target_tab="tasks",
        target_type="task",
        target_id=task.id,
        extra={"taskName": task.title},
    )

    _log_activity(team, request.user, "updated" if is_update else "created", "task", task.id, task.title,
                  f"{_actor_name(request.user)} {'updated' if is_update else 'created'} task '{task.title}'")

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
        task.column = columns[board_id_fe - 1]
        task.save(update_fields=["column"])
        _notify_team(
            team,
            request.user,
            f"{_actor_name(request.user)} moved task '{task.title}' to {task.column.name}.",
            event_type="task_moved",
            target_tab="tasks",
            target_type="task",
            target_id=task.id,
            extra={"toColumn": task.column.name},
        )
        _log_activity(team, request.user, "moved", "task", task.id, task.title,
                      f"{_actor_name(request.user)} moved task '{task.title}' to {task.column.name}")

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
    previous_members = []
    if proj_id:
        try:
            project = Project.objects.get(id=proj_id, team=team)
        except Project.DoesNotExist:
            return JsonResponse({"ok": False, "error": "Project not found"}, status=404)
        previous_members = project.members if isinstance(project.members, list) else []
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

    _notify_team(
        team,
        request.user,
        f"{_actor_name(request.user)} {'updated' if is_update else 'created'} project '{project.name}'.",
        event_type="project_updated" if is_update else "project_created",
        target_tab="projects",
        target_type="project",
        target_id=project.id,
        extra={"projectName": project.name},
    )

    _log_activity(team, request.user, "updated" if is_update else "created", "project", project.id, project.name,
                  f"{_actor_name(request.user)} {'updated' if is_update else 'created'} project '{project.name}'")

    if is_update:
        before = {str(m).lower() for m in previous_members}
        added_members = [m for m in cleaned_members if str(m).lower() not in before]
        if added_members:
            _notify_team(
                team,
                request.user,
                f"{_actor_name(request.user)} added member(s) to project '{project.name}': {', '.join(added_members)}.",
                event_type="project_member_added",
                target_tab="projects",
                target_type="project",
                target_id=project.id,
                extra={"projectName": project.name, "members": added_members},
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


@require_POST
@login_required
def api_workspace_file_upload(request):
    team, membership = _get_user_team(request.user)
    if not team:
        return JsonResponse({"ok": False, "error": "No team"}, status=400)

    up = request.FILES.get("file")
    if not up:
        return JsonResponse({"ok": False, "error": "No file"}, status=400)

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


# =========================
# ACTIVITY LOG API
# =========================

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


# =========================
# TASK COMMENTS API
# =========================

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

    _log_activity(team, request.user, "commented", "task", task.id, task.title,
                  f"{_actor_name(request.user)} commented on '{task.title}'")

    _notify_team(
        team, request.user,
        f"{_actor_name(request.user)} commented on task '{task.title}'.",
        event_type="task_comment", target_tab="tasks", target_type="task", target_id=task.id,
        extra={"taskName": task.title},
    )

    return JsonResponse({
        "ok": True,
        "comment": {
            "id": comment.id,
            "body": comment.body,
            "author": _actor_name(comment.author),
            "createdAt": comment.created_at.isoformat(),
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


# =========================
# TASK ATTACHMENTS API
# =========================

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


# =========================
# SUBTASKS / CHECKLISTS API
# =========================

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


# =========================
# ENHANCED ANALYTICS API
# =========================

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

    # Project stats
    projects = Project.objects.filter(team=team)
    project_stats = {
        "total": projects.count(),
        "active": projects.filter(status="active").count(),
        "completed": projects.filter(status="completed").count(),
        "archived": projects.filter(status="archived").count(),
    }

    return JsonResponse({"ok": True, "data": {
        "totalTasks": len(all_tasks),
        "overdue": overdue,
        "columns": col_data,
        "priority": priority_counts,
        "creationTrend": creation_trend,
        "completionTrend": completion_trend,
        "memberWorkload": member_workload,
        "projectStats": project_stats,
    }})


# =========================
# CALENDAR API
# =========================

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


# =========================
# EXPORT APIs
# =========================

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


def error_404(request, exception=None):
    return render(request, "core/404.html", status=404)


def error_500(request):
    return render(request, "core/500.html", status=500)
