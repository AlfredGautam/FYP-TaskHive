"""
Management command: run_scheduler

Runs a simple background scheduler that triggers deadline reminder emails
at a configurable interval (default: every 6 hours).

Usage:
    python manage.py run_scheduler
    python manage.py run_scheduler --interval 3600   # every 1 hour
"""

import time
import threading
from datetime import datetime

from django.core.management import call_command
from django.core.management.base import BaseCommand


DEFAULT_INTERVAL = 6 * 3600  # 6 hours


class Command(BaseCommand):
    help = "Run a lightweight scheduler for periodic tasks (deadline reminders, backups)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--interval",
            type=int,
            default=DEFAULT_INTERVAL,
            help="Seconds between each deadline-reminder run (default: 21600 = 6h).",
        )

    def handle(self, *args, **options):
        interval = options["interval"]
        self.stdout.write(
            self.style.SUCCESS(
                f"[TaskHive Scheduler] Started. Running deadline reminders every {interval}s."
            )
        )

        try:
            while True:
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                self.stdout.write(f"[{now}] Running send_deadline_reminders...")
                try:
                    call_command("send_deadline_reminders")
                except Exception as exc:
                    self.stderr.write(self.style.ERROR(f"  Error: {exc}"))
                self.stdout.write(f"[{now}] Next run in {interval}s.")
                time.sleep(interval)
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("\n[TaskHive Scheduler] Stopped."))
