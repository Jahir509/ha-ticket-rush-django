#!/usr/bin/env bash
# Deploy this checkout to /opt/ha-ticket-rush-django on Rocky Linux 10 and
# (re)start the systemd services.
#
# Run it on the server from a checkout of this repo:
#   git pull && scripts/deploy.sh
#
# Safe to run again. Each run:
#   1. rsyncs the checkout into /opt/ha-ticket-rush-django (--delete, so
#      files removed from the repo disappear there too). .env and .venv on
#      the server are never touched by the sync.
#   2. creates the "ticketrush" system user, the venv and .env on first run
#   3. pip installs requirements.txt and runs migrations
#   4. installs the units from deploy/systemd and restarts them
#
# --web-only (or scripts/deploy_only_web.sh) installs and runs gunicorn
# only. Any drain instance on this host is stopped and disabled, for web
# nodes behind a load balancer while the drain runs somewhere else.
#
# Re-executes itself under sudo when not run as root.
set -euo pipefail

DEST=/opt/ha-ticket-rush-django
APP_USER=ticketrush
PYTHON=${PYTHON:-python3}
WEB_UNIT=ticketrush-dj-web.service
DRAIN_UNIT=ticketrush-dj-drain@.service

WEB_ONLY=0
for arg in "$@"; do
  case $arg in
    --web-only) WEB_ONLY=1 ;;
    *) echo "Unknown option: $arg" >&2; exit 2 ;;
  esac
done

if [ "$(id -u)" -ne 0 ]; then
  exec sudo --preserve-env=PYTHON "$0" "$@"
fi

SRC=$(cd "$(dirname "$0")/.." && pwd)
if [ "$SRC" = "$DEST" ]; then
  echo "Run this from a checkout, not from $DEST itself." >&2
  exit 1
fi

log() { printf '\n==> %s\n' "$*"; }

log "Checking packages"
missing=()
command -v rsync >/dev/null || missing+=(rsync)
command -v curl >/dev/null || missing+=(curl)
command -v "$PYTHON" >/dev/null || missing+=(python3)
if [ ${#missing[@]} -gt 0 ]; then
  dnf -y install "${missing[@]}"
fi

log "Ensuring system user '$APP_USER'"
if ! id -u "$APP_USER" >/dev/null 2>&1; then
  useradd --system --home-dir "$DEST" --no-create-home \
    --shell /sbin/nologin "$APP_USER"
fi

log "Syncing $SRC -> $DEST"
mkdir -p "$DEST"
# Code is owned by root and only readable by the service user, so a
# compromised worker cannot rewrite the app. Excluded paths are also
# protected from --delete, which is what keeps .env and .venv alive.
rsync -rlpt --delete --chown=root:root \
  --exclude='.git/' \
  --exclude='.venv/' \
  --exclude='venv/' \
  --exclude='.env' \
  --exclude='__pycache__/' \
  --exclude='*.py[cod]' \
  --exclude='.vscode/' \
  --exclude='.idea/' \
  --exclude='staticfiles/' \
  --exclude='media/' \
  "$SRC/" "$DEST/"

if [ ! -f "$DEST/.env" ]; then
  if [ -f "$SRC/.env" ]; then
    seed="$SRC/.env"
  else
    seed="$SRC/.env.example"
  fi
  log "No $DEST/.env yet, seeding it from $seed"
  echo "    Edit it (passwords, SECRET_KEY, WORKERS) and run this again."
  cp "$seed" "$DEST/.env"
fi
# Holds DB passwords: root writes it, the service user only reads it.
chown "root:$APP_USER" "$DEST/.env"
chmod 640 "$DEST/.env"

log "Installing Python dependencies"
if [ ! -x "$DEST/.venv/bin/python" ]; then
  "$PYTHON" -m venv "$DEST/.venv"
fi
export PIP_ROOT_USER_ACTION=ignore PIP_DISABLE_PIP_VERSION_CHECK=1
"$DEST/.venv/bin/python" -m pip install --quiet --upgrade pip
"$DEST/.venv/bin/python" -m pip install --quiet -r "$DEST/requirements.txt"
# The service user cannot write __pycache__ into root-owned dirs, so
# compile here once instead of on every worker start.
"$DEST/.venv/bin/python" -m compileall -q "$DEST/ticketrush" "$DEST/tickets" "$DEST/users"

# Fresh files under /opt already get the right label, but a copied or
# moved-in file keeps its old one. Cheap to reset every time.
if command -v restorecon >/dev/null && selinuxenabled 2>/dev/null; then
  restorecon -R "$DEST"
fi

log "Running migrations"
(
  cd "$DEST"
  runuser -u "$APP_USER" -- bash -c \
    'set -a; . ./.env; set +a; exec .venv/bin/python manage.py migrate --noinput'
)

log "Installing systemd units"
install -m 644 "$DEST/deploy/systemd/$WEB_UNIT" /etc/systemd/system/
if [ "$WEB_ONLY" -eq 0 ]; then
  install -m 644 "$DEST/deploy/systemd/$DRAIN_UNIT" /etc/systemd/system/
fi
systemctl daemon-reload

log "Restarting services"
systemctl enable --quiet "$WEB_UNIT"
systemctl restart "$WEB_UNIT"
if [ "$WEB_ONLY" -eq 0 ]; then
  systemctl enable --quiet ticketrush-dj-drain@1.service
  # Every drain instance that is loaded, so extra ones started by hand
  # (drain@2, drain@3, ...) pick up the new code too.
  systemctl restart 'ticketrush-dj-drain@*.service' ticketrush-dj-drain@1.service
  status_units=("$WEB_UNIT" 'ticketrush-dj-drain@*.service')
  journal_units=(-u "$WEB_UNIT" -u 'ticketrush-dj-drain@*')
else
  # Running ones show up in list-units, enabled-but-stopped ones only as
  # symlinks in a .wants directory. disable needs exact names, no globs.
  mapfile -t drains < <(
    {
      systemctl list-units --all --plain --no-legend 'ticketrush-dj-drain@*.service' | awk '{print $1}'
      find /etc/systemd/system -path '*.wants/ticketrush-dj-drain@*.service' -printf '%f\n'
    } | grep -v '^ticketrush-dj-drain@\.service$' | sort -u
  )
  if [ ${#drains[@]} -gt 0 ]; then
    echo "    Web-only: stopping and disabling ${drains[*]}"
    systemctl disable --now --quiet "${drains[@]}"
  fi
  status_units=("$WEB_UNIT")
  journal_units=(-u "$WEB_UNIT")
fi

log "Checking /readyz"
bind=$(sed -n 's/^BIND=//p' "$DEST/.env" | tail -n1)
bind=${bind:-unix:/run/ticketrush-dj/gunicorn.sock}
if [[ $bind == unix:* ]]; then
  check=(curl -fsS --unix-socket "${bind#unix:}" http://localhost/readyz)
else
  check=(curl -fsS "http://${bind/0.0.0.0/127.0.0.1}/readyz")
fi
for _ in $(seq 1 20); do
  if "${check[@]}" 2>/dev/null; then
    echo
    systemctl --no-pager --lines=0 status "${status_units[@]}" || true
    log "Deployed."
    exit 0
  fi
  sleep 0.5
done

echo "readyz did not answer. Recent logs:" >&2
journalctl --no-pager -n 30 "${journal_units[@]}" >&2
exit 1
