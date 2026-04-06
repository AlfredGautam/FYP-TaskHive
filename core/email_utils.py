"""
TaskHive Email Utilities
Provides formatted HTML email senders for:
- Welcome email on registration
- Task assignment notification
- Deadline reminder notification
"""

import html as _html
import logging
import threading
import time

from django.core.mail import EmailMultiAlternatives
from django.conf import settings

MAX_EMAIL_RETRIES = 2
RETRY_DELAY_SECONDS = 1

logger = logging.getLogger(__name__)


def _from_email():
    return (
        getattr(settings, "DEFAULT_FROM_EMAIL", None)
        or getattr(settings, "EMAIL_HOST_USER", None)
        or "taskhive65@gmail.com"
    )


def _site_url():
    return getattr(settings, "SITE_URL", "http://127.0.0.1:8000").rstrip("/")


def _esc(value):
    """HTML-escape a user-supplied string."""
    return _html.escape(str(value)) if value else ""


def _send_html_email(subject, text_body, html_body, recipient_list):
    """Send an email with both plain-text and HTML alternatives.
    Retries up to MAX_EMAIL_RETRIES times on transient failures."""
    last_exc = None
    for attempt in range(1, MAX_EMAIL_RETRIES + 2):  # 1 initial + retries
        try:
            msg = EmailMultiAlternatives(
                subject=subject,
                body=text_body,
                from_email=_from_email(),
                to=recipient_list,
            )
            msg.attach_alternative(html_body, "text/html")
            msg.send(fail_silently=False)
            logger.info("Email sent successfully to %s | subject=%s (attempt %d)", recipient_list, subject, attempt)
            return True
        except Exception as exc:
            last_exc = exc
            logger.warning(
                "Email attempt %d/%d failed for %s | error=%s",
                attempt, MAX_EMAIL_RETRIES + 1, recipient_list, exc,
            )
            if attempt <= MAX_EMAIL_RETRIES:
                time.sleep(RETRY_DELAY_SECONDS)

    logger.error(
        "All %d attempts failed to send email to %s | subject=%s | error=%s",
        MAX_EMAIL_RETRIES + 1, recipient_list, subject, last_exc,
        exc_info=True,
    )
    return False


def _send_html_email_async(subject, text_body, html_body, recipient_list):
    """Fire-and-forget email sending in a background thread."""
    thread = threading.Thread(
        target=_send_html_email,
        args=(subject, text_body, html_body, recipient_list),
        daemon=True,
    )
    thread.start()
    return True


# ---------------------------------------------------------------------------
# Shared HTML base template
# ---------------------------------------------------------------------------

def _base_html(subtitle, content_html, header_gradient="linear-gradient(135deg, #06b6d4 0%, #3b82f6 100%)"):
    """Wrap email content in the shared TaskHive HTML shell."""
    site = _site_url()
    sender = _esc(_from_email())
    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <style>
    body {{ font-family: 'Segoe UI', Arial, sans-serif; background: #0f172a; margin: 0; padding: 0; }}
    .wrapper {{ max-width: 600px; margin: 40px auto; background: #1e293b; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 24px rgba(0,0,0,0.4); }}
    .header {{ background: {header_gradient}; padding: 32px 40px; text-align: center; }}
    .header h1 {{ color: #ffffff; margin: 0; font-size: 26px; letter-spacing: 1px; }}
    .header p {{ color: rgba(255,255,255,0.85); margin: 6px 0 0; font-size: 14px; }}
    .body {{ padding: 36px 40px; color: #cbd5e1; }}
    .body h2 {{ color: #f1f5f9; font-size: 19px; margin-top: 0; }}
    .body p {{ line-height: 1.7; font-size: 15px; }}
    .features {{ background: #0f172a; border-radius: 8px; padding: 20px 24px; margin: 24px 0; }}
    .features li {{ color: #94a3b8; margin: 8px 0; font-size: 14px; }}
    .task-card {{ background: #0f172a; border-left: 4px solid #06b6d4; border-radius: 8px; padding: 20px 24px; margin: 20px 0; }}
    .task-card .task-title {{ color: #f1f5f9; font-size: 18px; font-weight: 700; margin: 0 0 12px; }}
    .badge {{ display: inline-block; padding: 4px 12px; border-radius: 999px; font-size: 12px; font-weight: 600; }}
    .meta-row {{ color: #94a3b8; font-size: 13px; margin: 6px 0; }}
    .meta-row strong {{ color: #cbd5e1; }}
    .alert-banner {{ border-radius: 8px; padding: 14px 20px; margin: 0 0 20px; font-weight: 700; font-size: 15px; text-align: center; }}
    .btn {{ display: inline-block; margin-top: 28px; padding: 14px 32px; background: linear-gradient(135deg, #06b6d4, #3b82f6); color: #ffffff !important; text-decoration: none; border-radius: 8px; font-weight: 600; font-size: 15px; }}
    .footer {{ text-align: center; padding: 20px 40px; color: #475569; font-size: 12px; border-top: 1px solid #334155; }}
  </style>
</head>
<body>
  <div class="wrapper">
    <div class="header">
      <h1>\U0001f41d TaskHive</h1>
      <p>{subtitle}</p>
    </div>
    <div class="body">
      {content_html}
    </div>
    <div class="footer">
      &copy; TaskHive &middot; Sent by {sender}
    </div>
  </div>
</body>
</html>"""


# ---------------------------------------------------------------------------
# 1. Welcome Email
# ---------------------------------------------------------------------------

def send_welcome_email(user_name: str, user_email: str):
    """Send a welcome email to a newly registered user."""
    safe_name = _esc(user_name)
    site = _site_url()
    subject = "Welcome to TaskHive!"

    text_body = (
        f"Hi {user_name},\n\n"
        "Welcome to TaskHive! We're thrilled to have you on board.\n\n"
        "With TaskHive you can:\n"
        "  \u2022 Create and manage teams\n"
        "  \u2022 Track tasks on collaborative boards\n"
        "  \u2022 Monitor project progress with analytics\n"
        "  \u2022 Collaborate using code space & file sharing\n\n"
        "Your account is ready. Jump in and start collaborating!\n\n"
        f"  \u27a1 Log in: {site}/\n\n"
        "--------------------------------------------\n"
        f"\u00a9 TaskHive | {_from_email()}\n"
        "\u2014 The TaskHive Team"
    )

    content = f"""
      <h2>Welcome aboard, {safe_name}! \U0001f44b</h2>
      <p>We're excited to have you join <strong>TaskHive</strong> &mdash; the place where teams get things done.</p>
      <div class="features">
        <ul>
          <li>\u2705 Create &amp; manage teams with ease</li>
          <li>\U0001f4cb Track tasks on collaborative Kanban boards</li>
          <li>\U0001f4ca Monitor project progress with real-time analytics</li>
          <li>\U0001f4ac Collaborate using our built-in code space &amp; file sharing</li>
        </ul>
      </div>
      <p>Your account is ready. Jump in and start collaborating!</p>
      <a href="{site}/" class="btn">Go to TaskHive &rarr;</a>"""

    html_body = _base_html("Collaborative Task Management", content)
    return _send_html_email_async(subject, text_body, html_body, [user_email])


# ---------------------------------------------------------------------------
# 2. Task Assignment Email
# ---------------------------------------------------------------------------

def send_task_assigned_email(
    assignee_name: str,
    assignee_email: str,
    task_title: str,
    team_name: str,
    assigned_by_name: str,
    due_date: str = "",
    priority: str = "",
):
    """Notify an assignee that a task has been assigned to them."""
    safe_name = _esc(assignee_name)
    safe_title = _esc(task_title)
    safe_team = _esc(team_name)
    safe_assigned_by = _esc(assigned_by_name)
    safe_due = _esc(due_date) if due_date else "Not set"
    priority_label = _esc(priority.capitalize()) if priority else "Medium"
    site = _site_url()

    subject = f"[TaskHive] You've been assigned a task: {task_title}"

    due_line = f"Due Date    : {due_date}" if due_date else "Due Date    : Not set"
    text_body = (
        f"Hi {assignee_name},\n\n"
        f"Your team '{team_name}' has assigned you a new task.\n\n"
        "--------------------------------------------\n"
        f"  Task        : {task_title}\n"
        f"  {due_line}\n"
        f"  Priority    : {priority_label}\n"
        f"  Assigned by : {assigned_by_name}\n"
        f"  Team        : {team_name}\n"
        "--------------------------------------------\n\n"
        "Please log in to TaskHive to review and start working on it.\n\n"
        f"  \u27a1 View tasks: {site}/workspace/\n\n"
        "--------------------------------------------\n"
        f"\u00a9 TaskHive | {_from_email()}\n"
        "\u2014 The TaskHive Team"
    )

    priority_colors = {
        "high": "#ef4444",
        "medium": "#f59e0b",
        "low": "#22c55e",
    }
    priority_color = priority_colors.get((priority or "medium").lower(), "#f59e0b")

    content = f"""
      <h2>Hi {safe_name}, you have a new task! \U0001f4cb</h2>
      <p>Your team <strong>{safe_team}</strong> has assigned you a task. Please check it out and start working on it.</p>
      <div class="task-card" style="border-left-color: #06b6d4;">
        <p class="task-title">{safe_title}</p>
        <div class="meta-row"><strong>Team:</strong> {safe_team}</div>
        <div class="meta-row"><strong>Assigned by:</strong> {safe_assigned_by}</div>
        <div class="meta-row"><strong>Due Date:</strong> {safe_due}</div>
        <div class="meta-row" style="margin-top:8px;">
          <span class="badge" style="background:{priority_color}22;color:{priority_color};border:1px solid {priority_color}55;">\u26a1 {priority_label} Priority</span>
        </div>
      </div>
      <p>Log in to TaskHive to view full task details, update its status, and collaborate with your team.</p>
      <a href="{site}/workspace/" class="btn">View My Tasks &rarr;</a>"""

    html_body = _base_html("New Task Assignment", content)
    return _send_html_email_async(subject, text_body, html_body, [assignee_email])


# ---------------------------------------------------------------------------
# 3. Deadline Reminder Email
# ---------------------------------------------------------------------------

def send_deadline_reminder_email(
    assignee_name: str,
    assignee_email: str,
    task_title: str,
    team_name: str,
    due_date: str,
    days_left: int,
):
    """Notify an assignee that their task deadline is approaching."""
    safe_name = _esc(assignee_name)
    safe_title = _esc(task_title)
    safe_team = _esc(team_name)
    safe_due = _esc(due_date)
    site = _site_url()
    days_word = "day" if days_left == 1 else "days"

    subject = f"[TaskHive] Deadline Reminder: '{task_title}' is due soon!"

    if days_left == 0:
        urgency = "TODAY"
        urgency_msg = "This task is due TODAY."
    elif days_left == 1:
        urgency = "TOMORROW"
        urgency_msg = "This task is due TOMORROW."
    else:
        urgency = f"in {days_left} {days_word}"
        urgency_msg = f"This task is due in {days_left} {days_word}."

    text_body = (
        f"Hi {assignee_name},\n\n"
        f"\u26a0 {urgency_msg}\n\n"
        "--------------------------------------------\n"
        f"  Task           : {task_title}\n"
        f"  Due Date       : {due_date}\n"
        f"  Days Remaining : {days_left} {days_word}\n"
        f"  Team           : {team_name}\n"
        "--------------------------------------------\n\n"
        "Please log in to TaskHive to review and update the task status.\n\n"
        f"  \u27a1 Check tasks: {site}/workspace/\n\n"
        "--------------------------------------------\n"
        f"\u00a9 TaskHive | {_from_email()}\n"
        "\u2014 The TaskHive Team"
    )

    if days_left == 0:
        urgency_color = "#ef4444"
        urgency_icon = "\U0001f534"
    elif days_left == 1:
        urgency_color = "#f59e0b"
        urgency_icon = "\U0001f7e0"
    else:
        urgency_color = "#06b6d4"
        urgency_icon = "\U0001f535"

    header_gradient = f"linear-gradient(135deg, {urgency_color} 0%, #1e40af 100%)"

    content = f"""
      <div class="alert-banner" style="background:{urgency_color}22;border:1px solid {urgency_color}55;color:{urgency_color};">{urgency_icon} Deadline approaching &mdash; due {_esc(urgency.upper())}</div>
      <h2>Hi {safe_name}, don't forget your task! \u23f0</h2>
      <p>Your team <strong>{safe_team}</strong> assigned you a task whose deadline is coming up soon.</p>
      <div class="task-card" style="border-left-color: {urgency_color};">
        <p class="task-title">{safe_title}</p>
        <div class="meta-row"><strong>Team:</strong> {safe_team}</div>
        <div class="meta-row"><strong>Due Date:</strong> {safe_due}</div>
        <div class="meta-row"><strong>Days Remaining:</strong> {days_left} {days_word}</div>
      </div>
      <p>Please log in to TaskHive to review and update the task status before the deadline.</p>
      <a href="{site}/workspace/" class="btn" style="background:linear-gradient(135deg,{urgency_color},#1e40af);">Check My Tasks &rarr;</a>"""

    html_body = _base_html("Deadline Reminder", content, header_gradient=header_gradient)
    return _send_html_email(subject, text_body, html_body, [assignee_email])


# ---------------------------------------------------------------------------
# 4. Team Invitation Email
# ---------------------------------------------------------------------------

def send_team_invitation_email(
    invitee_name: str,
    invitee_email: str,
    team_name: str,
    invited_by_name: str,
    accept_url: str,
    decline_url: str,
):
    """Send an invitation email with Accept / Decline links."""
    safe_name = _esc(invitee_name)
    safe_team = _esc(team_name)
    safe_by = _esc(invited_by_name)
    site = _site_url()

    subject = f"[TaskHive] You've been invited to join team '{team_name}'"

    text_body = (
        f"Hi {invitee_name},\n\n"
        f"{invited_by_name} has invited you to join the team '{team_name}' on TaskHive.\n\n"
        "You can accept or decline this invitation using the links below:\n\n"
        f"  Accept:  {accept_url}\n"
        f"  Decline: {decline_url}\n\n"
        "If you did not expect this invitation, you can safely ignore this email.\n\n"
        "--------------------------------------------\n"
        f"\u00a9 TaskHive | {_from_email()}\n"
        "\u2014 The TaskHive Team"
    )

    content = f"""
      <h2>Hi {safe_name}, you've been invited! \u2709\ufe0f</h2>
      <p><strong>{safe_by}</strong> has invited you to join the team <strong>{safe_team}</strong> on TaskHive.</p>
      <div class="task-card" style="border-left-color: #06b6d4;">
        <p class="task-title">{safe_team}</p>
        <div class="meta-row"><strong>Invited by:</strong> {safe_by}</div>
        <div class="meta-row"><strong>Role:</strong> Team Member</div>
      </div>
      <p>Click a button below to respond to this invitation:</p>
      <div style="text-align:center;margin:28px 0;">
        <a href="{_esc(accept_url)}" class="btn" style="background:linear-gradient(135deg,#22c55e,#16a34a);margin-right:12px;">
          \u2705 Accept Invitation
        </a>
        <a href="{_esc(decline_url)}" class="btn" style="background:linear-gradient(135deg,#ef4444,#dc2626);">
          \u274c Decline
        </a>
      </div>
      <p style="font-size:13px;color:#94a3b8;">If you did not expect this invitation, you can safely ignore this email.</p>"""

    html_body = _base_html("Team Invitation", content, header_gradient="linear-gradient(135deg, #06b6d4 0%, #8b5cf6 100%)")
    return _send_html_email_async(subject, text_body, html_body, [invitee_email])