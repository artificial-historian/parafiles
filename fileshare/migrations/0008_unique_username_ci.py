from django.db import migrations, models
from django.db.models import Count
from django.db.models.functions import Lower


def check_case_duplicate_usernames(apps, schema_editor):
    user_model = apps.get_model("fileshare", "User")
    duplicates = (
        user_model.objects.annotate(username_ci=Lower("username"))
        .values("username_ci")
        .annotate(total=Count("id"))
        .filter(total__gt=1)
    )
    if duplicates.exists():
        sample = ", ".join(item["username_ci"] for item in duplicates[:5])
        raise RuntimeError(
            "Cannot enforce case-insensitive usernames until duplicate accounts are "
            f"renamed or merged. Conflicting lowercase username(s): {sample}"
        )


class Migration(migrations.Migration):

    dependencies = [
        ("fileshare", "0007_user_email_verified_at_user_pending_email_and_more"),
    ]

    operations = [
        migrations.RunPython(check_case_duplicate_usernames, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="user",
            constraint=models.UniqueConstraint(Lower("username"), name="unique_username_ci"),
        ),
    ]
