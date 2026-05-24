from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from fileshare.services.health import operations_health


class Command(BaseCommand):
    help = "Check Parafiles operational dependencies."

    def add_arguments(self, parser):
        parser.add_argument(
            "--fail-on-warn",
            action="store_true",
            help="Exit nonzero when any check reports a warning.",
        )

    def handle(self, *args, **options):
        status, checks = operations_health()
        for check in checks:
            self.stdout.write(f"{check.status.upper():5} {check.name}: {check.detail}")
        self.stdout.write(f"Overall: {status.upper()}")
        if status == "error" or (status == "warn" and options["fail_on_warn"]):
            raise CommandError(f"Operations health is {status}.")
