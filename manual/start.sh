#!/usr/bin/env bash
# Start the Django app with gunicorn in the foreground. Ctrl+C stops it.
#
#   manual/start.sh                    # settings from manual/gunicorn.conf.py
#   BIND=0.0.0.0:9000 WORKERS=4 manual/start.sh
set -euo pipefail

cd "$(dirname "$0")/.."

# One-time setup, if .venv does not exist yet:
#   python3 -m venv .venv
#   .venv/bin/pip install -r requirements.txt
#   set -a; . ./.env; set +a; .venv/bin/python manage.py migrate

exec .venv/bin/gunicorn -c manual/gunicorn.conf.py
