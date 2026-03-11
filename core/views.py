import json
import random
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.hashers import make_password, check_password
from django.contrib.auth.models import User
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST

from .models import CodeFile, PasswordOTP


# =========================
# PAGES
# =========================

def dashboard_page(request):
    # Public landing page (dashboard.html)
    return render(request, "core/dashboard.html")


@ensure_csrf_cookie
def login_page(request):
    # Public login page
    return render(request, "core/login.html")


@login_required
def user_page(request):
    # After login/register user setup page
    return render(request, "core/user.html")


@login_required
def workspace(request):
    # Main board page (index.html)
    return render(request, "core/index.html")


@login_required
def analytics_page(request):
    return render(request, "core/analytics.html")


@ensure_csrf_cookie
@login_required
def codespace_page(request):
    # Monaco editor page
    return render(request, "core/codespace.html")


@login_required
def profile_page(request):
    return render(request, "core/profile.html")


# =========================
# AUTH APIs
# =========================

@login_required
def api_me(request):
    u = request.user
    return JsonResponse({
        "ok": True,
        "user": {
            "name": (u.first_name or u.username),
            "email": (u.email or u.username),
            "username": u.username,
        }
    })


@require_POST
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
        return JsonResponse({"ok": False, "error": "Invalid credentials"}, status=401)

    login(request, user)

    # Always go to /user/ first
    return JsonResponse({"ok": True, "redirect": "/user/"})


@require_POST
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

    # we use email as username
    if User.objects.filter(username=email).exists():
        return JsonResponse({"ok": False, "error": "User already exists"}, status=409)

    user = User.objects.create_user(username=email, email=email, password=password)
    user.first_name = name
    user.save()

    login(request, user)

    # After register also go /user/
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
def api_code_upload(request):
    """
    Upload file -> store in DB (filename + content).
    Allows many files.
    """
    up = request.FILES.get("file")
    if not up:
        return JsonResponse({"ok": False, "error": "No file uploaded"}, status=400)

    try:
        text = up.read().decode("utf-8", errors="ignore")
    except Exception:
        text = ""

    # Always create new file (many files allowed)
    f = CodeFile.objects.create(
        owner=request.user,
        filename=up.name,
        content=text
    )

    return JsonResponse({"ok": True, "file_id": f.id, "filename": f.filename})


@require_POST
@login_required
def api_code_save(request):
    """
    Save editor content into existing DB file
    """
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


# =========================
# FORGOT PASSWORD (OTP)
# =========================

def _gen_otp():
    return f"{random.randint(0, 999999):06d}"


@require_POST
def api_password_request_otp(request):
    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"ok": False, "error": "Invalid JSON"}, status=400)

    email = (data.get("email") or "").strip().lower()
    if not email:
        return JsonResponse({"ok": False, "error": "Email required"}, status=400)

    # Your users are created with username=email
    if not User.objects.filter(username=email).exists():
        return JsonResponse({"ok": False, "error": "No account found with this email."}, status=404)

    otp = _gen_otp()
    expires = timezone.now() + timedelta(minutes=10)

    # invalidate previous OTPs
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

    # sender must be configured in settings.py (EMAIL_HOST_USER)
    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", None) or getattr(settings, "EMAIL_HOST_USER", None)

    try:
        send_mail(subject, message, from_email, [email], fail_silently=False)
    except Exception as e:
        return JsonResponse({"ok": False, "error": f"Email send failed: {str(e)}"}, status=500)

    return JsonResponse({"ok": True})


@require_POST
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

    user.set_password(new_password)
    user.save()

    record.used = True
    record.save(update_fields=["used"])

    return JsonResponse({"ok": True})

from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from .models import UserProfile

@login_required
def api_me(request):
    u = request.user
    profile, _ = UserProfile.objects.get_or_create(user=u)

    return JsonResponse({
        "ok": True,
        "user": {
            "name": u.first_name,
            "email": u.email,
            "displayName": profile.display_name,
            "username": profile.username,
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

@login_required
def api_profile_update(request):
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "POST required"}, status=405)

    profile, _ = UserProfile.objects.get_or_create(user=request.user)

    # normal fields from POST
    profile.display_name = request.POST.get("displayName", profile.display_name)
    profile.username = request.POST.get("username", profile.username)
    profile.tagline = request.POST.get("tagline", profile.tagline)
    profile.bio = request.POST.get("bio", profile.bio)
    profile.github = request.POST.get("github", profile.github)
    profile.linkedin = request.POST.get("linkedin", profile.linkedin)
    profile.theme_mode = request.POST.get("themeMode", profile.theme_mode)
    profile.accent_color = request.POST.get("accentColor", profile.accent_color)

    # file uploads
    if request.FILES.get("photo"):
        profile.photo = request.FILES["photo"]
    if request.FILES.get("cover"):
        profile.cover_photo = request.FILES["cover"]

    profile.save()

    # also update Django user fields
    request.user.first_name = request.POST.get("name", request.user.first_name)
    request.user.email = request.POST.get("email", request.user.email)
    request.user.save()

    return JsonResponse({"ok": True})
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from .models import UserProfile

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
