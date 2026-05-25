#!/bin/sh
set -eu

APP_DIR="${PARAFILES_APP_DIR:-/srv/parafiles/app}"
VENV_DIR="${PARAFILES_VENV_DIR:-/srv/parafiles/venv}"
ENV_FILE="${PARAFILES_ENV_FILE:-/srv/parafiles/.env}"

set -a
. "$ENV_FILE"
set +a

cd "$APP_DIR"
exec "$VENV_DIR/bin/python" manage.py reset_site "$@"
