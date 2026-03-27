from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone


class Team(models.Model):
    name = models.CharField(max_length=120)
    code = models.CharField(max_length=20, unique=True, db_index=True)
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name="teams_created")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["code"]),
        ]

    def __str__(self):
        return self.name


class TeamMembership(models.Model):
    ROLE_HEAD = "head"
    ROLE_MEMBER = "member"
    ROLE_CHOICES = [
        (ROLE_HEAD, "Head"),
        (ROLE_MEMBER, "Member"),
    ]

    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="team_memberships")
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default=ROLE_MEMBER)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["team", "user"], name="unique_team_user"),
        ]
        indexes = [
            models.Index(fields=["team", "role"]),
            models.Index(fields=["user", "joined_at"]),
        ]

    def __str__(self):
        return f"{self.team_id}:{self.user_id} ({self.role})"


class Workspace(models.Model):
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="workspaces")
    name = models.CharField(max_length=160)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="workspaces_created")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["team", "name"], name="unique_workspace_name_per_team"),
        ]
        indexes = [
            models.Index(fields=["team", "-updated_at"]),
        ]

    def __str__(self):
        return f"{self.team_id} - {self.name}"


class Board(models.Model):
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="boards")
    name = models.CharField(max_length=160)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="boards_created")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["workspace", "name"], name="unique_board_name_per_workspace"),
        ]
        indexes = [
            models.Index(fields=["workspace", "-updated_at"]),
        ]

    def __str__(self):
        return f"{self.workspace_id} - {self.name}"


class Column(models.Model):
    board = models.ForeignKey(Board, on_delete=models.CASCADE, related_name="columns")
    name = models.CharField(max_length=120)
    position = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["position", "id"]
        constraints = [
            models.UniqueConstraint(fields=["board", "name"], name="unique_column_name_per_board"),
        ]
        indexes = [
            models.Index(fields=["board", "position"]),
        ]

    def __str__(self):
        return f"{self.board_id} - {self.name}"


class Task(models.Model):
    PRIORITY_HIGH = "high"
    PRIORITY_MEDIUM = "medium"
    PRIORITY_LOW = "low"
    PRIORITY_CHOICES = [
        (PRIORITY_HIGH, "High"),
        (PRIORITY_MEDIUM, "Medium"),
        (PRIORITY_LOW, "Low"),
    ]

    TYPE_NORMAL = "normal"
    TYPE_SUPER = "super"
    TYPE_CHOICES = [
        (TYPE_NORMAL, "Normal"),
        (TYPE_SUPER, "Super"),
    ]

    board = models.ForeignKey(Board, on_delete=models.CASCADE, related_name="tasks")
    column = models.ForeignKey(Column, on_delete=models.CASCADE, related_name="tasks")

    title = models.CharField(max_length=220)
    description = models.TextField(blank=True, default="")

    due_date = models.DateField(null=True, blank=True)
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default=PRIORITY_MEDIUM)
    task_type = models.CharField(max_length=10, choices=TYPE_CHOICES, default=TYPE_NORMAL)
    labels = models.JSONField(default=list, blank=True)

    assignees = models.ManyToManyField(User, related_name="tasks_assigned", blank=True)

    position = models.PositiveIntegerField(default=0)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="tasks_created")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["position", "-updated_at", "-created_at"]
        indexes = [
            models.Index(fields=["board", "column", "position"]),
            models.Index(fields=["board", "-updated_at"]),
            models.Index(fields=["due_date"]),
        ]

    def __str__(self):
        return f"{self.board_id}:{self.title}"


class Project(models.Model):
    STATUS_ACTIVE = "active"
    STATUS_COMPLETED = "completed"
    STATUS_ARCHIVED = "archived"
    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Active"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_ARCHIVED, "Archived"),
    ]

    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="projects")
    name = models.CharField(max_length=220)
    description = models.TextField(blank=True, default="")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    members = models.JSONField(default=list, blank=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="projects_created")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-created_at"]
        indexes = [
            models.Index(fields=["team", "-updated_at"]),
        ]

    def __str__(self):
        return f"{self.team_id}:{self.name}"


class ProjectFile(models.Model):
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="project_files")
    name = models.CharField(max_length=255)
    file_type = models.CharField(max_length=50, blank=True, default="")
    size = models.CharField(max_length=50, blank=True, default="")
    file = models.FileField(upload_to="project_files/", blank=True, null=True)
    uploaded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="uploaded_files")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["team", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.team_id}:{self.name}"


class ApprovalRequest(models.Model):
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="approval_requests")
    entity_type = models.CharField(max_length=20)  # 'task' or 'project'
    action = models.CharField(max_length=20)  # 'create', 'update', 'delete'
    payload = models.JSONField(default=dict, blank=True)
    target_id = models.IntegerField(null=True, blank=True)
    summary = models.CharField(max_length=300, blank=True, default="")
    requested_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="approval_requests_made")
    requested_by_name = models.CharField(max_length=120, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["team", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.team_id}:{self.entity_type}:{self.action}"


class Notification(models.Model):
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="notifications")
    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name="notifications")
    actor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="notifications_sent")

    message = models.CharField(max_length=300)
    event_type = models.CharField(max_length=40, blank=True, default="")

    target_tab = models.CharField(max_length=20, blank=True, default="")
    target_type = models.CharField(max_length=20, blank=True, default="")
    target_id = models.IntegerField(null=True, blank=True)

    extra = models.JSONField(default=dict, blank=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["team", "recipient", "-created_at"]),
            models.Index(fields=["recipient", "is_read", "-created_at"]),
        ]

    def __str__(self):
        return f"notif:{self.team_id}:{self.recipient_id}:{self.event_type}"


class TaskComment(models.Model):
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="task_comments")
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [
            models.Index(fields=["task", "created_at"]),
        ]

    def __str__(self):
        return f"comment:{self.task_id}:{self.author_id}"


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


class EmailVerificationOTP(models.Model):
    """OTP records used to verify email before creating a new account."""

    name = models.CharField(max_length=120)
    email = models.EmailField(db_index=True)
    password_hash = models.CharField(max_length=128)
    otp_hash = models.CharField(max_length=128)

    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    used = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["email", "used", "-created_at"]),
        ]

    def is_expired(self) -> bool:
        return timezone.now() > self.expires_at

    def __str__(self):
        return f"verify:{self.email} used={self.used}"


class UserProfile(models.Model):
    """
    Stores profile page fields + images in DB.
    This makes profile persist after logout/login.
    """
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")

    current_team = models.ForeignKey(
        Team,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="current_for_profiles",
    )

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
