import json
from django.contrib import admin
from django.contrib.auth.models import User
from django.db.models import Count, Q
from django.urls import path
from django.http import JsonResponse
from django.template.response import TemplateResponse
from django.core.paginator import Paginator
from django.views.decorators.http import require_POST
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from .models import (
    UserProfile, Team, TeamMembership,
)


# =====================================================================
#  CUSTOM ADMIN SITE — single-page Team Management Dashboard
# =====================================================================
class TaskHiveAdminSite(admin.AdminSite):
    site_header = "🧊 TaskHive Administration"
    site_title = "TaskHive Admin"
    index_title = "Team Management"
    login_template = "admin/admin_login.html"

    def has_permission(self, request):
        """Require user to be active, staff, AND superuser to access admin."""
        return (
            request.user.is_active
            and request.user.is_staff
            and request.user.is_superuser
        )

    def get_urls(self):
        custom = [
            path("", self.admin_view(self.dashboard_view), name="index"),
            path("api/members/", self.admin_view(self.api_members), name="api_members"),
            path("api/teams/", self.admin_view(self.api_teams), name="api_teams"),
            path("api/member/add/", self.admin_view(self.api_member_add), name="api_member_add"),
            path("api/member/<int:pk>/delete/", self.admin_view(self.api_member_delete), name="api_member_delete"),
            path("api/member/<int:pk>/", self.admin_view(self.api_member_detail), name="api_member_detail"),
            path("api/member/<int:pk>/update/", self.admin_view(self.api_member_update), name="api_member_update"),
        ]
        return custom + super().get_urls()

    # ── dashboard page ──
    def dashboard_view(self, request):
        context = {
            **self.each_context(request),
            "title": "Team Management",
        }
        return TemplateResponse(request, "admin/dashboard.html", context)

    # ── API: paginated member list with search/filter/sort ──
    def api_members(self, request):
        qs = TeamMembership.objects.select_related("user", "user__profile", "team").all()

        # search
        q = request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(
                Q(user__username__icontains=q)
                | Q(user__first_name__icontains=q)
                | Q(user__last_name__icontains=q)
                | Q(user__email__icontains=q)
                | Q(team__name__icontains=q)
            )

        # filter role
        role = request.GET.get("role", "")
        if role in ("head", "member"):
            qs = qs.filter(role=role)

        # filter status
        status = request.GET.get("status", "")
        if status == "active":
            qs = qs.filter(user__is_active=True)
        elif status == "inactive":
            qs = qs.filter(user__is_active=False)

        # sort
        sort = request.GET.get("sort", "date_desc")
        if sort == "date_asc":
            qs = qs.order_by("team__created_at")
        elif sort == "name_asc":
            qs = qs.order_by("user__first_name", "user__last_name")
        elif sort == "name_desc":
            qs = qs.order_by("-user__first_name", "-user__last_name")
        else:
            qs = qs.order_by("-team__created_at")

        # stats (computed before pagination)
        total_users = User.objects.count()
        total_teams = Team.objects.count()
        active_members = TeamMembership.objects.filter(user__is_active=True).count()
        admin_count = TeamMembership.objects.filter(role="head").count()

        # paginate
        page_num = int(request.GET.get("page", 1))
        paginator = Paginator(qs, 10)
        page = paginator.get_page(page_num)

        rows = []
        for m in page:
            u = m.user
            profile = getattr(u, "profile", None)
            rows.append({
                "id": m.id,
                "user_id": u.id,
                "username": u.get_full_name() or u.username,
                "email": u.email,
                "role": m.role,
                "role_display": m.get_role_display(),
                "team_name": m.team.name,
                "team_id": m.team.id,
                "team_created": m.team.created_at.strftime("%b %d, %Y %I:%M %p"),
                "status": "active" if u.is_active else "inactive",
                "last_login": u.last_login.strftime("%b %d, %Y %I:%M %p") if u.last_login else "Never",
            })

        return JsonResponse({
            "rows": rows,
            "stats": {
                "total_users": total_users,
                "total_teams": total_teams,
                "active_members": active_members,
                "admin_count": admin_count,
            },
            "page": page.number,
            "num_pages": paginator.num_pages,
            "total": paginator.count,
        })

    # ── API: all teams (for dropdown) ──
    def api_teams(self, request):
        teams = Team.objects.order_by("name").values("id", "name")
        return JsonResponse({"teams": list(teams)})

    # ── API: member detail ──
    def api_member_detail(self, request, pk):
        try:
            m = TeamMembership.objects.select_related("user", "team").get(pk=pk)
        except TeamMembership.DoesNotExist:
            return JsonResponse({"error": "Not found"}, status=404)
        u = m.user
        return JsonResponse({
            "id": m.id,
            "user_id": u.id,
            "username": u.username,
            "full_name": u.get_full_name(),
            "email": u.email,
            "role": m.role,
            "team_name": m.team.name,
            "team_id": m.team.id,
            "status": "active" if u.is_active else "inactive",
            "last_login": u.last_login.strftime("%b %d, %Y %I:%M %p") if u.last_login else "Never",
            "date_joined": u.date_joined.strftime("%b %d, %Y %I:%M %p"),
        })

    # ── API: add member ──
    @method_decorator(require_POST)
    def api_member_add(self, request):
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)

        username = data.get("username", "").strip()
        email = data.get("email", "").strip()
        team_id = data.get("team_id")
        role = data.get("role", "member")

        if not username or not email or not team_id:
            return JsonResponse({"error": "username, email, and team_id are required"}, status=400)

        try:
            team = Team.objects.get(pk=team_id)
        except Team.DoesNotExist:
            return JsonResponse({"error": "Team not found"}, status=404)

        user, created = User.objects.get_or_create(
            email=email,
            defaults={"username": username, "first_name": username},
        )
        if created:
            user.set_unusable_password()
            user.save()

        if TeamMembership.objects.filter(team=team, user=user).exists():
            return JsonResponse({"error": "User already in this team"}, status=400)

        TeamMembership.objects.create(team=team, user=user, role=role)
        return JsonResponse({"ok": True})

    # ── API: update member ──
    @method_decorator(require_POST)
    def api_member_update(self, request, pk):
        try:
            m = TeamMembership.objects.select_related("user").get(pk=pk)
        except TeamMembership.DoesNotExist:
            return JsonResponse({"error": "Not found"}, status=404)

        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)

        if "role" in data:
            m.role = data["role"]
            m.save(update_fields=["role"])
        if "status" in data:
            m.user.is_active = data["status"] == "active"
            m.user.save(update_fields=["is_active"])

        return JsonResponse({"ok": True})

    # ── API: delete member ──
    @method_decorator(require_POST)
    def api_member_delete(self, request, pk):
        deleted, _ = TeamMembership.objects.filter(pk=pk).delete()
        if not deleted:
            return JsonResponse({"error": "Not found"}, status=404)
        return JsonResponse({"ok": True})


taskhive_admin = TaskHiveAdminSite(name="admin")
