from __future__ import annotations

import shutil
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = (
        "Reset Parafiles site data using the configured Django settings. "
        "By default this clears database rows only."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--remove-files",
            action="store_true",
            help=(
                "Also remove all files below PARAFILES_STORAGE_ROOT and "
                "PARAFILES_UPLOAD_SESSION_ROOT."
            ),
        )
        parser.add_argument(
            "--noinput",
            "--no-input",
            action="store_true",
            help="Run without an interactive confirmation prompt.",
        )

    def handle(self, *args, **options):
        remove_files = options["remove_files"]
        noinput = options["noinput"]
        database = settings.DATABASES["default"]
        storage_roots = [
            Path(settings.PARAFILES_STORAGE_ROOT),
            Path(settings.PARAFILES_UPLOAD_SESSION_ROOT),
        ]

        self.stdout.write("This will reset Parafiles using the active app settings.")
        self.stdout.write(f"Database engine: {database.get('ENGINE')}")
        self.stdout.write(f"Database name: {database.get('NAME')}")
        if remove_files:
            self.stdout.write("File data will also be removed from:")
            for root in storage_roots:
                self.stdout.write(f"  - {root}")
        else:
            self.stdout.write("File data will be left untouched.")

        if not noinput:
            expected = "reset site"
            confirmation = input(f"Type '{expected}' to continue: ")
            if confirmation != expected:
                raise CommandError("Reset cancelled.")

        call_command("flush", interactive=False, verbosity=0)
        self.stdout.write(self.style.SUCCESS("Database rows cleared."))

        if remove_files:
            for root in storage_roots:
                self.clear_directory(root)
                self.stdout.write(self.style.SUCCESS(f"File data cleared: {root}"))

    def clear_directory(self, root: Path) -> None:
        try:
            resolved_root = root.resolve()
        except OSError as exc:
            raise CommandError(f"Cannot resolve storage path {root}: {exc}") from exc

        if resolved_root == Path(resolved_root.anchor) or not str(resolved_root):
            raise CommandError(f"Refusing to clear unsafe storage root: {resolved_root}")

        resolved_root.mkdir(parents=True, exist_ok=True)
        for child in resolved_root.iterdir():
            try:
                if child.is_dir() and not child.is_symlink():
                    shutil.rmtree(child)
                else:
                    child.unlink()
            except OSError as exc:
                raise CommandError(f"Could not remove {child}: {exc}") from exc
