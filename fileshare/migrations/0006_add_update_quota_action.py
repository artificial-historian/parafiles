from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("fileshare", "0005_user_moderation_actions"),
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
                    ("update_quota", "Update quota"),
                ],
                max_length=32,
            ),
        ),
    ]
