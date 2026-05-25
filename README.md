# Parafiles

Parafiles is a Django monolith for invite-only Paralives mod file sharing. Uploaders manage private folder trees and share unlisted, revocable links to files or folders. Downloaders do not need accounts and can only access direct links.

## Local Setup

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
copy .env.example .env
.\.venv\Scripts\python manage.py migrate
.\.venv\Scripts\python manage.py createsuperuser
.\.venv\Scripts\python manage.py runserver
```

The default development configuration uses SQLite and local private storage under `var/`. Production should set `DATABASE_URL`, `REDIS_URL`, and private storage paths outside the web root.

## Native Server Deployment

The primary deployment path is a native Linux server with host-managed PostgreSQL and Nginx. Use:

- [deploy/README_NATIVE.md](deploy/README_NATIVE.md) for the full install and operations runbook.
- [deploy/parafiles.env.example](deploy/parafiles.env.example) for `/srv/parafiles/.env`.
- [deploy/gunicorn.service](deploy/gunicorn.service), [deploy/celery.service](deploy/celery.service), [deploy/parafiles-cleanup.service](deploy/parafiles-cleanup.service), and [deploy/parafiles-cleanup.timer](deploy/parafiles-cleanup.timer) for systemd.
- [deploy/nginx.conf](deploy/nginx.conf) for Nginx with internal protected downloads.

Minimal deployment flow:

```powershell
copy deploy\parafiles.env.example .env
python manage.py check --deploy
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py check_operations_health
```

On the server, run those commands as the dedicated `parafiles` user through the helper documented in the native runbook.

## Production Notes

- Put uploaded files outside the app and web roots.
- Serve downloads through Django authorization plus Nginx `X-Accel-Redirect`.
- Run a Celery worker for scan jobs.
- Schedule `python manage.py cleanup_uploads` or the `cleanup_expired_uploads_task` Celery task to clear expired staged upload chunks.
- Run `python manage.py check_operations_health` during deployment to verify database, cache, storage, scanner, and worker settings.
- Run ClamAV locally and configure `PARAFILES_CLAMAV_COMMAND`.
- Configure `PARAFILES_SIGNATURE_PRIVATE_KEY` and publish the matching Ed25519 public key so `.sig` downloads can be verified.
- Configure `VIRUSTOTAL_API_KEY` for hash reputation checks. Full file submission is disabled unless `VIRUSTOTAL_SUBMIT_FILES=true`.
- Configure Django email settings and `DEFAULT_FROM_EMAIL` so uploader invitations, email verification, and account recovery can be delivered.
- Keep admin access behind HTTPS. `PARAFILES_ADMIN_2FA_REQUIRED` defaults to true when `DJANGO_DEBUG=false`; staff users must first sign in through `/accounts/login/` and enroll a TOTP authenticator before moderation or admin access.

## Core Flows

- Staff or admin creates and emails a single-use invite.
- Uploader registers from the invite URL and verifies a recovery email address.
- Uploader creates folders, uploads chunked files, waits for scanning, and enables public shares.
- Anonymous downloader opens `/file/<slug>/` or `/folder/<slug>/`, then downloads through a short-lived token.
- Downloader can report abusive content from the public page.
- Staff can triage reports, hide/quarantine/restore content, regenerate links, soft-delete, or purge files.
