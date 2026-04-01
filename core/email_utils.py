"""
TaskHive Email Utilities
Provides formatted HTML email senders for:
- Welcome email on registration
- Task assignment notification
- Deadline reminder notification
"""

import logging

from django.core.mail import EmailMultiAlternatives
from django.conf import settings

logger = logging.getLogger(__name__)


def _from_email():
    return (
        getattr(settings, "DEFAULT_FROM_EMAIL", None)
        or getattr(settings, "EMAIL_HOST_USER", None)
        or "taskhive65@gmail.com"
    )


def _send_html_email(subject, text_body, html_body, recipient_list):
    """Send an email with both plain-text and HTML alternatives."""
    try:
        msg = EmailMultiAlternatives(
            subject=subject,
            body=text_body,
            from_email=_from_email(),
            to=recipient_list,
        )
        msg.attach_alternative(html_body, "text/html")
        msg.send(fail_silently=False)
        logger.info("Email sent successfully to %s | subject=%s", recipient_list, subject)
        return True
    except Exception as exc:
        logger.error(
            "Failed to send email to %s | subject=%s | error=%s",
            recipient_list, subject, exc,
            exc_info=True,
        )
        return False


# ---------------------------------------------------------------------------
# 1. Welcome Email
# ---------------------------------------------------------------------------

def send_welcome_email(user_name: str, user_email: str):
    """Send a welcome email to a newly registered user."""
    subject = "Welcome to TaskHive!"

    text_body = (
        f"Hi {user_name},\n\n"
        "Welcome to TaskHive! We're thrilled to have you on board.\n\n"
        "With TaskHive you can:\n"
        "  • Create and manage teams\n"
        "  • Track tasks on collaborative boards\n"
        "  • Monitor project progress with analytics\n\n"
        "Get started by logging in at http://127.0.0.1:8000/\n\n"
        "— The TaskHive Team"
    )

    html_body = f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <style>
    body {{ font-family: 'Segoe UI', Arial, sans-serif; background: #0f172a; margin: 0; padding: 0; }}
    .wrapper {{ max-width: 600px; margin: 40px auto; background: #1e293b; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 24px rgba(0,0,0,0.4); }}
    .header {{ background: linear-gradient(135deg, #06b6d4 0%, #3b82f6 100%); padding: 36px 40px; text-align: center; }}
    .header h1 {{ color: #ffffff; margin: 0; font-size: 28px; letter-spacing: 1px; }}
    .header p {{ color: #e0f2fe; margin: 8px 0 0; font-size: 15px; }}
    .body {{ padding: 36px 40px; color: #cbd5e1; }}
    .body h2 {{ color: #f1f5f9; font-size: 20px; margin-top: 0; }}
    .body p {{ line-height: 1.7; font-size: 15px; }}
    .features {{ background: #0f172a; border-radius: 8px; padding: 20px 24px; margin: 24px 0; }}
    .features li {{ color: #94a3b8; margin: 8px 0; font-size: 14px; }}
    .btn {{ display: inline-block; margin-top: 24px; padding: 14px 32px; background: linear-gradient(135deg, #06b6d4, #3b82f6); color: #ffffff !important; text-decoration: none; border-radius: 8px; font-weight: 600; font-size: 15px; }}
    .footer {{ text-align: center; padding: 20px 40px; color: #475569; font-size: 12px; border-top: 1px solid #334155; }}
  </style>
</head>
<body>
  <div class="wrapper">
    <div class="header">
      <h1>🐝 TaskHive</h1>
      <p>Collaborative Task Management</p>
    </div>
    <div class="body">
      <h2>Welcome aboard, {user_name}! 👋</h2>
      <p>We're excited to have you join <strong>TaskHive</strong> — the place where teams get things done.</p>
      <div class="features">
        <ul>
          <li>✅ Create &amp; manage teams with ease</li>
          <li>📋 Track tasks on collaborative Kanban boards</li>
          <li>📊 Monitor project progress with real-time analytics</li>
          <li>💬 Collaborate using our built-in code space &amp; file sharing</li>
        </ul>
      </div>
      <p>Your account is ready. Jump in and start collaborating!</p>
      <a href="http://127.0.0.1:8000/" class="btn">Go to TaskHive →</a>
    </div>
    <div class="footer">
      © TaskHive · You received this because you registered at taskhive65@gmail.com
    </div>
  </div>
</body>
</html>
"""
    return _send_html_email(subject, text_body, html_body, [user_email])


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
    subject = f"[TaskHive] You've been assigned a task: {task_title}"

    due_line = f"Due Date : {due_date}" if due_date else "Due Date : Not set"
    priority_label = priority.capitalize() if priority else "Medium"

    text_body = (
        f"Hi {assignee_name},\n\n"
        f"Your team '{team_name}' has assigned you a new task.\n\n"
        f"Task     : {task_title}\n"
        f"{due_line}\n"
        f"Priority : {priority_label}\n"
        f"Assigned by: {assigned_by_name}\n\n"
        "Please log in to TaskHive to review and start working on it.\n\n"
        "— The TaskHive Team"
    )

    priority_colors = {
        "high": "#ef4444",
        "medium": "#f59e0b",
        "low": "#22c55e",
    }
    priority_color = priority_colors.get((priority or "medium").lower(), "#f59e0b")

    html_body = f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <style>
    body {{ font-family: 'Segoe UI', Arial, sans-serif; background: #0f172a; margin: 0; padding: 0; }}
    .wrapper {{ max-width: 600px; margin: 40px auto; background: #1e293b; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 24px rgba(0,0,0,0.4); }}
    .header {{ background: linear-gradient(135deg, #06b6d4 0%, #3b82f6 100%); padding: 32px 40px; text-align: center; }}
    .header h1 {{ color: #ffffff; margin: 0; font-size: 26px; letter-spacing: 1px; }}
    .header p {{ color: #e0f2fe; margin: 6px 0 0; font-size: 14px; }}
    .body {{ padding: 36px 40px; color: #cbd5e1; }}
    .body h2 {{ color: #f1f5f9; font-size: 19px; margin-top: 0; }}
    .body p {{ line-height: 1.7; font-size: 15px; }}
    .task-card {{ background: #0f172a; border-left: 4px solid #06b6d4; border-radius: 8px; padding: 20px 24px; margin: 20px 0; }}
    .task-card .task-title {{ color: #f1f5f9; font-size: 18px; font-weight: 700; margin: 0 0 12px; }}
    .task-meta {{ display: flex; flex-wrap: wrap; gap: 12px; margin-top: 12px; }}
    .badge {{ display: inline-block; padding: 4px 12px; border-radius: 999px; font-size: 12px; font-weight: 600; }}
    .priority-badge {{ background: {priority_color}22; color: {priority_color}; border: 1px solid {priority_color}55; }}
    .meta-row {{ color: #94a3b8; font-size: 13px; margin: 6px 0; }}
    .meta-row strong {{ color: #cbd5e1; }}
    .btn {{ display: inline-block; margin-top: 28px; padding: 14px 32px; background: linear-gradient(135deg, #06b6d4, #3b82f6); color: #ffffff !important; text-decoration: none; border-radius: 8px; font-weight: 600; font-size: 15px; }}
    .footer {{ text-align: center; padding: 20px 40px; color: #475569; font-size: 12px; border-top: 1px solid #334155; }}
  </style>
</head>
<body>
  <div class="wrapper">
    <div class="header">
      <h1>🐝 TaskHive</h1>
      <p>New Task Assignment</p>
    </div>
    <div class="body">
      <h2>Hi {assignee_name}, you have a new task! 📋</h2>
      <p>Your team <strong>{team_name}</strong> has assigned you a task. Please check it out and start working on it.</p>
      <div class="task-card">
        <p class="task-title">{task_title}</p>
        <div class="meta-row"><strong>Team:</strong> {team_name}</div>
        <div class="meta-row"><strong>Assigned by:</strong> {assigned_by_name}</div>
        <div class="meta-row"><strong>Due Date:</strong> {due_date if due_date else 'Not set'}</div>
        <div class="meta-row" style="margin-top:8px;">
          <span class="badge priority-badge">⚡ {priority_label} Priority</span>
        </div>
      </div>
      <p>Log in to TaskHive to view full task details, update its status, and collaborate with your team.</p>
      <a href="http://127.0.0.1:8000/workspace/" class="btn">View My Tasks →</a>
    </div>
    <div class="footer">
      © TaskHive · Sent because you were assigned a task by your team
    </div>
  </div>
</body>
</html>
"""
    return _send_html_email(subject, text_body, html_body, [assignee_email])


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
    subject = f"[TaskHive] Deadline Reminder: '{task_title}' is due soon!"

    if days_left == 0:
        urgency = "TODAY"
        urgency_msg = "This task is due TODAY."
    elif days_left == 1:
        urgency = "TOMORROW"
        urgency_msg = "This task is due TOMORROW."
    else:
        urgency = f"in {days_left} days"
        urgency_msg = f"This task is due in {days_left} days."

    text_body = (
        f"Hi {assignee_name},\n\n"
        f"This is a reminder that a task assigned to you by team '{team_name}' is due {urgency}.\n\n"
        f"Task     : {task_title}\n"
        f"Due Date : {due_date}\n"
        f"Team     : {team_name}\n\n"
        f"{urgency_msg}\n\n"
        "Please log in to TaskHive to check the task status.\n\n"
        "— The TaskHive Team"
    )

    if days_left == 0:
        urgency_color = "#ef4444"
        urgency_icon = "🔴"
    elif days_left == 1:
        urgency_color = "#f59e0b"
        urgency_icon = "🟠"
    else:
        urgency_color = "#06b6d4"
        urgency_icon = "🔵"

    html_body = f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <style>
    body {{ font-family: 'Segoe UI', Arial, sans-serif; background: #0f172a; margin: 0; padding: 0; }}
    .wrapper {{ max-width: 600px; margin: 40px auto; background: #1e293b; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 24px rgba(0,0,0,0.4); }}
    .header {{ background: linear-gradient(135deg, {urgency_color} 0%, #1e40af 100%); padding: 32px 40px; text-align: center; }}
    .header h1 {{ color: #ffffff; margin: 0; font-size: 26px; letter-spacing: 1px; }}
    .header p {{ color: rgba(255,255,255,0.85); margin: 6px 0 0; font-size: 14px; }}
    .body {{ padding: 36px 40px; color: #cbd5e1; }}
    .body h2 {{ color: #f1f5f9; font-size: 19px; margin-top: 0; }}
    .body p {{ line-height: 1.7; font-size: 15px; }}
    .alert-banner {{ background: {urgency_color}22; border: 1px solid {urgency_color}55; border-radius: 8px; padding: 14px 20px; margin: 0 0 20px; color: {urgency_color}; font-weight: 700; font-size: 15px; text-align: center; }}
    .task-card {{ background: #0f172a; border-left: 4px solid {urgency_color}; border-radius: 8px; padding: 20px 24px; margin: 20px 0; }}
    .task-card .task-title {{ color: #f1f5f9; font-size: 18px; font-weight: 700; margin: 0 0 12px; }}
    .meta-row {{ color: #94a3b8; font-size: 13px; margin: 6px 0; }}
    .meta-row strong {{ color: #cbd5e1; }}
    .btn {{ display: inline-block; margin-top: 28px; padding: 14px 32px; background: linear-gradient(135deg, {urgency_color}, #1e40af); color: #ffffff !important; text-decoration: none; border-radius: 8px; font-weight: 600; font-size: 15px; }}
    .footer {{ text-align: center; padding: 20px 40px; color: #475569; font-size: 12px; border-top: 1px solid #334155; }}
  </style>
</head>
<body>
  <div class="wrapper">
    <div class="header">
      <h1>🐝 TaskHive</h1>
      <p>Deadline Reminder</p>
    </div>
    <div class="body">
      <div class="alert-banner">{urgency_icon} Deadline approaching — due {urgency.upper()}</div>
      <h2>Hi {assignee_name}, don't forget your task! ⏰</h2>
      <p>Your team <strong>{team_name}</strong> assigned you a task whose deadline is coming up soon.</p>
      <div class="task-card">
        <p class="task-title">{task_title}</p>
        <div class="meta-row"><strong>Team:</strong> {team_name}</div>
        <div class="meta-row"><strong>Due Date:</strong> {due_date}</div>
        <div class="meta-row"><strong>Days Remaining:</strong> {days_left} day(s)</div>
      </div>
      <p>Please log in to TaskHive to review and update the task status before the deadline.</p>
      <a href="http://127.0.0.1:8000/workspace/" class="btn">Check My Tasks →</a>
    </div>
    <div class="footer">
      © TaskHive · This is an automated deadline reminder from TaskHive
    </div>
  </div>
</body>
</html>
"""
    return _send_html_email(subject, text_body, html_body, [assignee_email])
