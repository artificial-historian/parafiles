from __future__ import annotations

from django.core.management.base import BaseCommand

from fileshare.services.cleanup import cleanup_expired_uploads


class Command(BaseCommand):
    help = "Clean expired upload sessions and stale staged upload chunks."

    def add_arguments(self, parser):
        parser.add_argument(
            "--orphan-age-seconds",
            type=int,
            default=None,
            help="Only delete orphan staged files older than this many seconds.",
        )

    def handle(self, *args, **options):
        result = cleanup_expired_uploads(orphan_age_seconds=options["orphan_age_seconds"])
        self.stdout.write(
            self.style.SUCCESS(
                "Expired sessions: {expired}; temp files: {temp}; orphan temp files: "
                "{orphans}; bytes deleted: {bytes}".format(
                    expired=result.expired_sessions,
                    temp=result.temp_files_deleted,
                    orphans=result.orphan_temp_files_deleted,
                    bytes=result.bytes_deleted,
                )
            )
        )
