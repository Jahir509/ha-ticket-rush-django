#!/usr/bin/env bash
# Deploy only the Django web service (gunicorn, ticketrush-dj-web.service).
# No drain worker is installed, and any drain instance already on this host
# is stopped and disabled. Everything else (sync, venv, .env, migrations,
# /readyz check) is the same as scripts/deploy.sh.
#
#   git pull && scripts/deploy_only_web.sh
exec "$(dirname "$0")/deploy.sh" --web-only "$@"
