from django.contrib import admin
from .models import CodeFile, PasswordOTP, UserProfile


@admin.register(CodeFile)
class CodeFileAdmin(admin.ModelAdmin):
    list_display = ("id", "owner", "filename", "updated_at", "created_at")
    list_filter = ("owner",)
    search_fields = ("filename", "owner__username", "owner__email")
    ordering = ("-updated_at",)


@admin.register(PasswordOTP)
class PasswordOTPAdmin(admin.ModelAdmin):
    list_display = ("id", "email", "user", "used", "created_at", "expires_at")
    list_filter = ("used",)
    search_fields = ("email", "user__username", "user__email")
    ordering = ("-created_at",)


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "display_name", "username_public", "theme_mode", "updated_at")
    search_fields = ("user__username", "user__email", "display_name", "username_public")
    ordering = ("-updated_at",)
