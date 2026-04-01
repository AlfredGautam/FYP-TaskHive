"""
Management command: backup_db

Creates a timestamped copy of the SQLite database file.

Usage:
    python manage.py backup_db
    python manage.py backup_db --output /path/to/backup/
"""

import shutil
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Create a timestamped backup of the SQLite database."

    def add_arguments(self, parser):
        parser.add_argument(
            "--output",
            type=str,
            default="",
            help="Directory to store the backup (default: project root /backups/).",
        )

    def handle(self, *args, **options):
        db_path = Path(settings.DATABASES["default"]["NAME"])
        if not db_path.exists():
            self.stderr.write(self.style.ERROR(f"Database not found: {db_path}"))
            return

        output_dir = Path(options["output"]) if options["output"] else (settings.BASE_DIR / "backups")
        output_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"db_backup_{timestamp}.sqlite3"
        backup_path = output_dir / backup_name

        shutil.copy2(db_path, backup_path)
        size_mb = backup_path.stat().st_size / (1024 * 1024)

        self.stdout.write(
            self.style.SUCCESS(
                f"[TaskHive] Backup created: {backup_path} ({size_mb:.2f} MB)"
            )
        )
