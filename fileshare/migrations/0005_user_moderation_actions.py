from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("fileshare", "0004_storedfile_changelog_storedfile_description_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name="moderationaction",
            name="action",
            field=models.CharField(
                choices=[
                    ("hide", "Hide"),
                    ("quarantine", "Quarantine"),
                    ("restore", "Restore"),
                    ("delete", "Delete"),
                    ("purge", "Purge"),
                    ("rescan", "Rescan"),
                    ("regenerate_share", "Regenerate share"),
                    ("resolve_report", "Resolve report"),
                    ("suspend_user", "Suspend user"),
                    ("restore_user", "Restore user"),
                    ("disable_uploads", "Disable uploads"),
                    ("disable_user_shares", "Disable user shares"),
                ],
                max_length=32,
            ),
        ),
        migrations.AddField(
            model_name="moderationaction",
            name="target_user",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="targeted_moderation_actions",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
