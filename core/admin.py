from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from .models import (
    CodeFile, PasswordOTP, EmailVerificationOTP, UserProfile,
    Team, TeamMembership, TeamInvitation,
    Workspace, Board, Column, Task, Project,
    ProjectFile, ApprovalRequest, Notification,
    TaskComment, ActivityLog, Subtask, TaskAttachment,
)

# ── Customize site header ──
admin.site.site_header = "🧊 TaskHive Administration"
admin.site.site_title = "TaskHive Admin"
admin.site.index_title = "Dashboard"


# ── Inline: UserProfile on User page ──
class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False
    verbose_name_plural = "Profile"
    fk_name = "user"


# ── Extend built-in User admin ──
class CustomUserAdmin(BaseUserAdmin):
    inlines = (UserProfileInline,)
    list_display = ("username", "email", "first_name", "is_active", "is_staff", "date_joined")
    list_filter = ("is_active", "is_staff", "is_superuser", "date_joined")


admin.site.unregister(User)
admin.site.register(User, CustomUserAdmin)


@admin.register(CodeFile)
class CodeFileAdmin(admin.ModelAdmin):
    list_display = ("id", "owner", "filename", "updated_at", "created_at")
    list_filter = ("owner",)
    search_fields = ("filename", "owner__username", "owner__email")
    ordering = ("-updated_at",)
    list_per_page = 25


@admin.register(PasswordOTP)
class PasswordOTPAdmin(admin.ModelAdmin):
    list_display = ("id", "email", "user", "used", "created_at", "expires_at")
    list_filter = ("used",)
    search_fields = ("email", "user__username", "user__email")
    ordering = ("-created_at",)
    list_per_page = 25


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "display_name", "username_public", "theme_mode", "updated_at")
    search_fields = ("user__username", "user__email", "display_name", "username_public")
    list_filter = ("theme_mode",)
    ordering = ("-updated_at",)
    list_per_page = 25


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "code", "created_by", "member_count", "created_at")
    search_fields = ("name", "code", "created_by__username", "created_by__email")
    ordering = ("-created_at",)
    list_per_page = 25

    def member_count(self, obj):
        return obj.memberships.count()
    member_count.short_description = "Members"


@admin.register(TeamMembership)
class TeamMembershipAdmin(admin.ModelAdmin):
    list_display = ("id", "team", "user", "role", "joined_at")
    list_filter = ("role",)
    search_fields = ("team__name", "team__code", "user__username", "user__email")
    ordering = ("-joined_at",)
    list_per_page = 25


@admin.register(TeamInvitation)
class TeamInvitationAdmin(admin.ModelAdmin):
    list_display = ("id", "team", "invited_user", "invited_by", "status", "created_at")
    list_filter = ("status",)
    search_fields = ("team__name", "invited_user__username", "invited_by__username")
    ordering = ("-created_at",)
    list_per_page = 25


@admin.register(Workspace)
class WorkspaceAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "team", "created_by", "created_at")
    search_fields = ("name", "team__name")
    list_filter = ("team",)
    ordering = ("-created_at",)
    list_per_page = 25


@admin.register(Board)
class BoardAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "workspace", "created_by", "created_at")
    search_fields = ("name", "workspace__name")
    ordering = ("-created_at",)
    list_per_page = 25


@admin.register(Column)
class ColumnAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "board", "position", "created_at")
    search_fields = ("name", "board__name")
    list_filter = ("board",)
    ordering = ("board", "position")
    list_per_page = 25


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "board", "column", "priority", "task_type", "is_blocked", "due_date", "created_by", "created_at")
    list_filter = ("priority", "task_type", "is_blocked")
    search_fields = ("title", "description", "board__name", "created_by__username")
    ordering = ("-created_at",)
    list_per_page = 25
    filter_horizontal = ("assignees", "blocked_by")


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "team", "status", "created_by", "created_at")
    list_filter = ("status",)
    search_fields = ("name", "description", "team__name")
    ordering = ("-created_at",)
    list_per_page = 25


@admin.register(ProjectFile)
class ProjectFileAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "file_type", "size", "team", "uploaded_by", "created_at")
    search_fields = ("name", "team__name")
    list_filter = ("file_type",)
    ordering = ("-created_at",)
    list_per_page = 25


@admin.register(ApprovalRequest)
class ApprovalRequestAdmin(admin.ModelAdmin):
    list_display = ("id", "team", "entity_type", "action", "summary", "requested_by_name", "created_at")
    list_filter = ("entity_type", "action")
    search_fields = ("summary", "team__name", "requested_by_name")
    ordering = ("-created_at",)
    list_per_page = 25


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("id", "recipient", "event_type", "message", "is_read", "created_at")
    list_filter = ("event_type", "is_read")
    search_fields = ("message", "recipient__username")
    ordering = ("-created_at",)
    list_per_page = 25


@admin.register(EmailVerificationOTP)
class EmailVerificationOTPAdmin(admin.ModelAdmin):
    list_display = ("id", "email", "name", "used", "created_at", "expires_at")
    list_filter = ("used",)
    search_fields = ("email", "name")
    ordering = ("-created_at",)
    list_per_page = 25


@admin.register(TaskComment)
class TaskCommentAdmin(admin.ModelAdmin):
    list_display = ("id", "task", "author", "short_body", "created_at")
    search_fields = ("body", "author__username", "task__title")
    ordering = ("-created_at",)
    list_per_page = 25

    def short_body(self, obj):
        return obj.body[:80] + "..." if len(obj.body) > 80 else obj.body
    short_body.short_description = "Comment"


# @admin.register(ActivityLog)
# class ActivityLogAdmin(admin.ModelAdmin):
#     list_display = ("id", "team", "actor", "action", "target_type", "target_name", "created_at")
#     list_filter = ("action", "target_type")
#     search_fields = ("target_name", "detail", "actor__username")
#     ordering = ("-created_at",)
#     list_per_page = 25


@admin.register(Subtask)
class SubtaskAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "task", "is_done", "position", "created_at")
    list_filter = ("is_done",)
    search_fields = ("title", "task__title")
    ordering = ("task", "position")
    list_per_page = 25


@admin.register(TaskAttachment)
class TaskAttachmentAdmin(admin.ModelAdmin):
    list_display = ("id", "original_name", "task", "file_size", "uploaded_by", "created_at")
    search_fields = ("original_name", "task__title")
    ordering = ("-created_at",)
    list_per_page = 25
