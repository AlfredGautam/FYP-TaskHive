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

    # Block admin/staff users from normal user login — they must use /admin/
    if user.is_staff or user.is_superuser:
        return JsonResponse(
            {"ok": False, "error": "Admin accounts cannot log in here. Please use the admin panel."},
            status=403,
        )

    login(request, user)
    return JsonResponse({"ok": True, "redirect": "/user/"})


@require_POST
def api_logout(request):
    logout(request)
    return JsonResponse({"ok": True})


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


def google_auth_start(request):
    """Step 1: Redirect the user to Google's OAuth2 consent screen."""
    import urllib.parse
    client_id = settings.GOOGLE_CLIENT_ID
    if not client_id:
        return redirect("/login/")

    state = secrets.token_hex(16)

    redirect_uri = "http://127.0.0.1:8000/auth/google/callback/"
    params = urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
    })
    response = redirect(f"https://accounts.google.com/o/oauth2/v2/auth?{params}")
    response.set_cookie("google_oauth_state", state, max_age=600, httponly=True, samesite="Lax")
    return response


def google_auth_callback(request):
    """Step 2: Google redirects here with an authorization code. Exchange it
    for an ID-token, find/create the user, and log them in."""
    import requests as http_requests
    import logging
    logger = logging.getLogger(__name__)

    error = request.GET.get("error")
    if error:
        logger.error(f"Google OAuth error: {error}")
        return HttpResponse(f"Google OAuth error: {error}", status=400)

    code = request.GET.get("code", "")
    state = request.GET.get("state", "")
    saved_state = request.COOKIES.get("google_oauth_state", "")

    logger.info(f"Google callback: code received={bool(code)}, state={state[:10]}..., saved_state={saved_state[:10]}...")

    if not code:
        logger.error("Missing authorization code")
        return HttpResponse("Missing authorization code", status=400)

    # Use the actual request host for redirect_uri (supports localhost, 127.0.0.1, etc.)
    scheme = request.scheme
    host = request.get_host()
    redirect_uri = f"{scheme}://{host}/auth/google/callback/"

    client_id = settings.GOOGLE_CLIENT_ID
    client_secret = settings.GOOGLE_CLIENT_SECRET

    logger.info(f"redirect_uri: {redirect_uri}")
    logger.info(f"client_id set: {bool(client_id)}, client_secret set: {bool(client_secret)}")

    if not client_id or not client_secret:
        logger.error("Google OAuth credentials not configured")
        return HttpResponse("Google OAuth credentials not configured. Please set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in environment variables.", status=500)

    # Exchange the authorization code for tokens
    token_resp = http_requests.post("https://oauth2.googleapis.com/token", data={
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }, timeout=10)

    logger.info(f"Token exchange status: {token_resp.status_code}")

    if token_resp.status_code != 200:
        logger.error(f"Token exchange failed: {token_resp.text}")
        return HttpResponse(
            f"Token exchange failed ({token_resp.status_code}): {token_resp.text}<br>redirect_uri used: {redirect_uri}",
            status=400,
        )

    token_data = token_resp.json()
    access_token = token_data.get("access_token", "")

    if not access_token:
        return HttpResponse("Google token response missing access_token", status=400)

    # Use the userinfo endpoint instead of JWT verification (avoids clock skew issues)
    userinfo_resp = http_requests.get(
        "https://www.googleapis.com/oauth2/v3/userinfo",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=10,
    )
    if userinfo_resp.status_code != 200:
        return HttpResponse(f"Failed to get user info: {userinfo_resp.text}", status=400)

    idinfo = userinfo_resp.json()
    email = (idinfo.get("email") or "").strip().lower()
    name = idinfo.get("name") or email.split("@")[0]

    if not email:
        return HttpResponse("Google account has no email", status=400)

    # Find or create user
    user = User.objects.filter(email__iexact=email).first()
    if user is None:
        user = User.objects.filter(username=email).first()
    if user is None:
        user = User.objects.create_user(username=email, email=email, first_name=name)
        user.set_unusable_password()
        user.save()
        try:
            from .email_utils import send_welcome_email
            send_welcome_email(user_name=name, user_email=email)
        except Exception:
            pass

    # Block admin/staff users from logging in via Google OAuth on the normal site
    if user.is_staff or user.is_superuser:
        return HttpResponse("Admin accounts cannot log in here. Please use the admin panel at /admin/.", status=403)

    try:
        login(request, user, backend="core.backends.EmailBackend")
    except Exception as e:
        return HttpResponse(f"Login failed: {e}", status=500)

    # The /user/ page checks localStorage for "taskhive_current_user" on the client side.
    # We must set it via a small redirect page so the dashboard doesn't bounce to /login/.
    display_name = user.get_full_name() or user.first_name or user.username
    html = (
        '<!DOCTYPE html><html><head><script>'
        'localStorage.setItem("taskhive_current_user", JSON.stringify({'
        f'"name": "{display_name}",'
        f'"email": "{email}",'
        '"lastLogin": new Date().toISOString()'
        '}));'
        'window.location.href = "/user/";'
        '</script></head><body>Redirecting...</body></html>'
    )
    response = HttpResponse(html, content_type="text/html")
    response.delete_cookie("google_oauth_state")
    return response


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


