from django.apps import AppConfig


class FileshareConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "fileshare"

    def ready(self):
        from . import checks  # noqa: F401
