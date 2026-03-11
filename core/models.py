from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone


class CodeFile(models.Model):
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="code_files")
    filename = models.CharField(max_length=255)
    content = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-created_at"]
        indexes = [
            models.Index(fields=["owner", "-updated_at"]),  # fast recent list per user
            models.Index(fields=["owner", "filename"]),     # fast search by filename per user
        ]

    def __str__(self):
        return f"{self.owner.username} - {self.filename}"


class PasswordOTP(models.Model):
    """
    OTP for password reset.
    Stores email + hashed otp. (Never store OTP plain text)
    """
    user = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="password_otps",
    )
    email = models.EmailField(db_index=True)
    otp_hash = models.CharField(max_length=128)

    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    used = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["email", "used", "-created_at"]),
            models.Index(fields=["user", "-created_at"]),
        ]

    def is_expired(self) -> bool:
        return timezone.now() > self.expires_at

    def __str__(self):
        return f"{self.email} - used={self.used}"


class UserProfile(models.Model):
    """
    Stores profile page fields + images in DB.
    This makes profile persist after logout/login.
    """
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")

    display_name = models.CharField(max_length=120, blank=True, default="")
    username_public = models.CharField(max_length=60, blank=True, default="")
    tagline = models.CharField(max_length=200, blank=True, default="")
    bio = models.TextField(blank=True, default="")

    github = models.URLField(blank=True, default="")
    linkedin = models.URLField(blank=True, default="")

    # images (saved under MEDIA_ROOT/profile/...)
    photo = models.ImageField(upload_to="profile/photos/", blank=True, null=True)
    cover_photo = models.ImageField(upload_to="profile/covers/", blank=True, null=True)

    # theme settings
    theme_mode = models.CharField(max_length=10, default="dark")  # dark/light
    accent_color = models.CharField(max_length=20, default="#22d3ee")

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["-updated_at"]),
        ]

    def __str__(self):
        return f"Profile: {self.user.username}"


# ✅ Auto-create profile when a new User is created
@receiver(post_save, sender=User)
def create_user_profile(sender, instance: User, created: bool, **kwargs):
    if created:
        UserProfile.objects.create(
            user=instance,
            display_name=instance.get_full_name() or instance.username,
            username_public=(instance.username.split("@")[0] if "@" in instance.username else instance.username),
        )


# ✅ If user updates, ensure profile still exists (safety)
@receiver(post_save, sender=User)
def save_user_profile(sender, instance: User, **kwargs):
    if not hasattr(instance, "profile"):
        UserProfile.objects.create(
            user=instance,
            display_name=instance.get_full_name() or instance.username,
            username_public=(instance.username.split("@")[0] if "@" in instance.username else instance.username),
        )
    else:
        instance.profile.save()
