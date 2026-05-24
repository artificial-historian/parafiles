from __future__ import annotations

from fileshare.models import AbuseReport, Folder, ModerationAction, PublicShare, StoredFile, User


def record_action(
    actor: User | None,
    action: str,
    *,
    stored_file: StoredFile | None = None,
    folder: Folder | None = None,
    share: PublicShare | None = None,
    report: AbuseReport | None = None,
    target_user: User | None = None,
    reason: str = "",
    metadata: dict | None = None,
) -> ModerationAction:
    return ModerationAction.objects.create(
        actor=actor if actor and actor.is_authenticated else None,
        action=action,
        stored_file=stored_file,
        folder=folder,
        share=share,
        report=report,
        target_user=target_user,
        reason=reason,
        metadata=metadata or {},
    )
