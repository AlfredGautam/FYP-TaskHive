"""
Management command: send_deadline_reminders

Sends deadline reminder notifications (in-app + Gmail) for tasks whose
due_date is within the next REMIND_DAYS days (default: 0, 1, 3).

Usage:
    python manage.py send_deadline_reminders
    python manage.py send_deadline_reminders --days 1 3 7
"""

from datetime import date, timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import Task, Notification, TeamMembership, Team
from core.email_utils import send_deadline_reminder_email


DEFAULT_REMIND_DAYS = [0, 1, 3]


class Command(BaseCommand):
    help = "Send deadline reminder emails and in-app notifications for upcoming task due dates."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            nargs="+",
            type=int,
            default=DEFAULT_REMIND_DAYS,
            help="Number of days ahead to trigger reminders (e.g. --days 0 1 3).",
        )

    def handle(self, *args, **options):
        remind_days = options["days"]
        today = date.today()
        target_dates = [today + timedelta(days=d) for d in remind_days]

        self.stdout.write(
            f"[TaskHive] Checking deadlines for dates: {[d.isoformat() for d in target_dates]}"
        )

        tasks = (
            Task.objects.filter(due_date__in=target_dates)
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
                    self.stdout.write(
                        f"  [SKIP] Already notified {assignee_email} for task '{task.title}' today."
                    )
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
                        self.stdout.write(
                            f"  [OK] Email sent to {assignee_email} for task '{task.title}' (due in {days_left}d)."
                        )
                    else:
                        self.stdout.write(
                            self.style.WARNING(
                                f"  [WARN] Email failed for {assignee_email} on task '{task.title}'."
                            )
                        )

        self.stdout.write(
            self.style.SUCCESS(
                f"[TaskHive] Done. {notifs_created} in-app notification(s), {emails_sent} email(s) sent."
            )
        )
