# Native Linux Server Deployment

This is the primary deployment path for a server that already has PostgreSQL and Nginx. Parafiles runs as a normal Django application under Gunicorn and Celery, with systemd managing processes and Nginx serving static files plus protected downloads through `X-Accel-Redirect`.

The examples assume this layout:

```text
/srv/parafiles/
  app/                 application source tree
  venv/                Python virtual environment
  .env                 systemd/Django environment file
  private_uploads/     stored uploaded bytes, outside the web root
  upload_sessions/     temporary chunked-upload staging files
```

Replace `parafiles.example.com` and paths if your server uses different conventions.

## Runtime Requirements

Required services:

- PostgreSQL 14 or newer, already running on the host or reachable over the network
- Redis 6 or newer for cache, throttles, temporary download tokens, and Celery broker
- Nginx with HTTPS configured
- Python 3.12 or newer with `venv`
- ClamAV with an up-to-date signature database
- SMTP credentials for invitation email delivery

Debian/Ubuntu package baseline:

```sh
sudo apt update
sudo apt install python3 python3-venv python3-pip python3-dev build-essential libpq-dev redis-server clamav clamav-daemon
```

If PostgreSQL and Nginx are already installed and managed, do not reinstall them. Confirm Redis is available unless you already have a remote Redis instance.

## System User And Directories

Create a dedicated service user and let Nginx read protected files through the shared group:

```sh
sudo adduser --system --group --home /srv/parafiles parafiles
sudo usermod -aG parafiles www-data
sudo install -d -o parafiles -g parafiles -m 2750 /srv/parafiles
sudo install -d -o parafiles -g parafiles -m 2750 /srv/parafiles/app
sudo install -d -o parafiles -g parafiles -m 2750 /srv/parafiles/app/staticfiles
sudo install -d -o parafiles -g parafiles -m 2770 /srv/parafiles/private_uploads
sudo install -d -o parafiles -g parafiles -m 2770 /srv/parafiles/upload_sessions
```

The service units use `UMask=0007`, so files created by Gunicorn and Celery remain readable by the `parafiles` group and not by other local users.

## PostgreSQL

If the existing PostgreSQL instance is local, create a role and database:

```sh
sudo -u postgres createuser parafiles --pwprompt
sudo -u postgres createdb -O parafiles parafiles
```

If the database is managed elsewhere, create an equivalent database and role there. The application uses `DATABASE_URL`, for example:

```text
DATABASE_URL=postgres://parafiles:password@127.0.0.1:5432/parafiles
```

URL-encode the password if it contains `@`, `:`, `/`, `#`, `%`, `?`, or other URL-reserved characters.

## Source And Python Environment

Copy or clone this source tree into `/srv/parafiles/app`, then install dependencies:

```sh
cd /srv/parafiles/app
sudo chown -R parafiles:parafiles /srv/parafiles/app
sudo -u parafiles python3 -m venv /srv/parafiles/venv
sudo -u parafiles /srv/parafiles/venv/bin/python -m pip install --upgrade pip wheel
sudo -u parafiles /srv/parafiles/venv/bin/python -m pip install -r requirements.txt
```

## Environment File

Install and edit the environment file:

```sh
sudo cp /srv/parafiles/app/deploy/parafiles.env.example /srv/parafiles/.env
sudo chown parafiles:parafiles /srv/parafiles/.env
sudo chmod 0640 /srv/parafiles/.env
sudo editor /srv/parafiles/.env
```

Set at minimum:

- `DJANGO_SECRET_KEY` to a long random value
- `DJANGO_ALLOWED_HOSTS` to the public hostname
- `DJANGO_CSRF_TRUSTED_ORIGINS` to the exact HTTPS origin
- `DATABASE_URL` for the existing PostgreSQL instance
- `REDIS_URL` for the Redis instance
- SMTP settings and `DEFAULT_FROM_EMAIL`
- `PARAFILES_STORAGE_ROOT=/srv/parafiles/private_uploads`
- `PARAFILES_UPLOAD_SESSION_ROOT=/srv/parafiles/upload_sessions`
- `PARAFILES_SERVE_PRIVATE_DOWNLOADS=false`
- `PARAFILES_INTERNAL_DOWNLOAD_PREFIX=/protected-files/`
- `PARAFILES_ADMIN_2FA_REQUIRED=true`

Keep `PARAFILES_ALLOW_SCAN_BYPASS=false` for native deployment. Uploads should remain unavailable until local scanning completes successfully.

Install the helper command for Django management tasks:

```sh
sudo install -o root -g root -m 0755 /srv/parafiles/app/deploy/run-manage.sh /usr/local/bin/parafiles-manage
```

## ClamAV

Make sure signatures are present before disabling scan bypass:

```sh
sudo freshclam
sudo systemctl enable --now clamav-daemon
sudo -u parafiles clamscan --version
```

The default `PARAFILES_CLAMAV_COMMAND=clamscan` is simple and reliable. If you switch to `clamdscan`, test it with the `parafiles` user and update the env file.

## Django Initialization

Run checks, migrations, and static collection:

```sh
sudo -u parafiles /usr/local/bin/parafiles-manage check --deploy
sudo -u parafiles /usr/local/bin/parafiles-manage migrate
sudo -u parafiles /usr/local/bin/parafiles-manage collectstatic --noinput
sudo -u parafiles /usr/local/bin/parafiles-manage check_operations_health
```

Create the first administrator:

```sh
sudo -u parafiles /usr/local/bin/parafiles-manage createsuperuser
```

Staff accounts must sign in through `/accounts/login/` and enroll a TOTP authenticator before accessing moderation or Django admin when `PARAFILES_ADMIN_2FA_REQUIRED=true`.

## systemd Services

Install the service units:

```sh
sudo cp /srv/parafiles/app/deploy/gunicorn.service /etc/systemd/system/parafiles-gunicorn.service
sudo cp /srv/parafiles/app/deploy/celery.service /etc/systemd/system/parafiles-celery.service
sudo cp /srv/parafiles/app/deploy/parafiles-cleanup.service /etc/systemd/system/parafiles-cleanup.service
sudo cp /srv/parafiles/app/deploy/parafiles-cleanup.timer /etc/systemd/system/parafiles-cleanup.timer
sudo systemctl daemon-reload
sudo systemctl enable --now parafiles-gunicorn parafiles-celery parafiles-cleanup.timer
```

Check status and logs:

```sh
sudo systemctl status parafiles-gunicorn parafiles-celery parafiles-cleanup.timer
sudo journalctl -u parafiles-gunicorn -f
sudo journalctl -u parafiles-celery -f
```

The Gunicorn socket is created at `/run/parafiles/gunicorn.sock`. Nginx must run as a user that is a member of the `parafiles` group.

## Nginx

Install the site template:

```sh
sudo cp /srv/parafiles/app/deploy/nginx.conf /etc/nginx/sites-available/parafiles
sudo editor /etc/nginx/sites-available/parafiles
sudo ln -s /etc/nginx/sites-available/parafiles /etc/nginx/sites-enabled/parafiles
sudo nginx -t
sudo systemctl reload nginx
```

Before reloading, update:

- `server_name`
- TLS certificate directives if your existing Nginx setup does not inject them elsewhere
- `client_max_body_size` if the per-file quota changes
- `alias /srv/parafiles/app/staticfiles/;` if `STATIC_ROOT` changes
- `alias /srv/parafiles/private_uploads/;` if `PARAFILES_STORAGE_ROOT` changes

The `/protected-files/` location must stay `internal`; otherwise uploaded files could be downloaded without Django authorization and throttling.

## Update Procedure

For each release:

```sh
cd /srv/parafiles/app
sudo -u parafiles git pull
sudo -u parafiles /srv/parafiles/venv/bin/python -m pip install -r requirements.txt
sudo -u parafiles /usr/local/bin/parafiles-manage check --deploy
sudo -u parafiles /usr/local/bin/parafiles-manage migrate
sudo -u parafiles /usr/local/bin/parafiles-manage collectstatic --noinput
sudo systemctl restart parafiles-celery
sudo systemctl reload parafiles-gunicorn
sudo -u parafiles /usr/local/bin/parafiles-manage check_operations_health
```

Use `restart parafiles-gunicorn` instead of `reload` if the reload does not pick up a changed dependency or process state.

## Backups

Back up all of these together:

- PostgreSQL database
- `/srv/parafiles/private_uploads`
- `/srv/parafiles/upload_sessions` if preserving in-flight uploads matters
- `/srv/parafiles/.env`

The database stores logical folder/file metadata, public share slugs, scan state, audit logs, reports, and quota overrides. The private upload directory stores the bytes. Restoring only one without the other will leave broken file references.

## Smoke Test Checklist

1. `parafiles-manage check --deploy` reports no errors.
2. `parafiles-manage check_operations_health` reports no errors. Warnings should be understood and accepted.
3. `/health/` returns JSON status `ok` through Nginx.
4. First admin can log in, enroll TOTP, and access `/moderation/`.
5. Staff can create an invitation.
6. An uploader can register from the invite, create folders, upload a small file, and enable sharing.
7. Anonymous access to `/file/<slug>/` works.
8. Download goes through `/download/prepare/<slug>/` and `/download/<token>/`.
9. Direct access to `/protected-files/...` returns 404 or 403 from Nginx.
10. Abuse report submission creates a report visible in moderation.
11. Hiding or quarantining a file makes the public download unavailable.

## Troubleshooting

- `502 Bad Gateway`: check `systemctl status parafiles-gunicorn`, socket permissions, and that `www-data` is in the `parafiles` group.
- `403` or `404` for downloads after token handoff: verify `PARAFILES_INTERNAL_DOWNLOAD_PREFIX` matches the Nginx `/protected-files/` location and that Nginx can read `/srv/parafiles/private_uploads`.
- Uploads remain unavailable: check `systemctl status parafiles-celery`, ClamAV availability, and scan result records in moderation.
- Invite email does not send: verify SMTP env settings and inspect Gunicorn logs.
- `check --deploy` fails on secret key: replace every placeholder in `/srv/parafiles/.env`.
- `check_operations_health` warns about direct private serving: set `PARAFILES_SERVE_PRIVATE_DOWNLOADS=false` and route through Nginx.
