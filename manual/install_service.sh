#!/usr/bin/env bash
# Install and start ticketrush-dj-gunicorn.service. Safe to run again.
#
#   manual/install_service.sh
#
# Steps: sync code to /opt, service user, venv + requirements, .env
# permissions, migrations, systemd unit, firewall port, /readyz check.
set -euo pipefail

DEST=/opt/ha-ticket-rush-django
APP_USER=ticketrush
UNIT=ticketrush-dj-gunicorn.service
PORT=8001

if [ "$(id -u)" -ne 0 ]; then
  exec sudo "$0" "$@"
fi

HERE=$(cd "$(dirname "$0")" && pwd)
log() { printf '\n==> %s\n' "$*"; }

log "Syncing code to $DEST"
"$HERE/sync.sh" >/dev/null

log "Service user '$APP_USER'"
if ! id -u "$APP_USER" >/dev/null 2>&1; then
  useradd --system --home-dir "$DEST" --no-create-home --shell /sbin/nologin "$APP_USER"
fi

log ".env"
if [ ! -f "$DEST/.env" ]; then
  echo "Missing $DEST/.env. Create it (copy .env.example and edit), then run again." >&2
  exit 1
fi
chown "root:$APP_USER" "$DEST/.env"
chmod 640 "$DEST/.env"

log "Virtualenv and requirements"
if [ ! -x "$DEST/.venv/bin/python" ]; then
  python3 -m venv "$DEST/.venv"
fi
export PIP_ROOT_USER_ACTION=ignore PIP_DISABLE_PIP_VERSION_CHECK=1
"$DEST/.venv/bin/python" -m pip install --quiet --upgrade pip
"$DEST/.venv/bin/python" -m pip install --quiet -r "$DEST/requirements.txt"
"$DEST/.venv/bin/python" -m compileall -q "$DEST/ticketrush" "$DEST/tickets" "$DEST/users" "$DEST/manual"
if command -v restorecon >/dev/null && selinuxenabled 2>/dev/null; then
  restorecon -R "$DEST"
fi

log "Migrations"
(cd "$DEST" && runuser -u "$APP_USER" -- bash -c \
  'set -a; . ./.env; set +a; exec .venv/bin/python manage.py migrate --noinput')

log "Installing $UNIT"
install -m 644 "$DEST/manual/$UNIT" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --quiet "$UNIT"
# Conflicts= in the unit stops ticketrush-dj-web.service; disable it too so
# it does not come back on reboot.
systemctl disable --quiet ticketrush-dj-web.service 2>/dev/null || true
systemctl restart "$UNIT"

if systemctl is-active --quiet firewalld; then
  log "Opening port $PORT/tcp in firewalld"
  firewall-cmd --quiet --permanent --add-port="$PORT/tcp"
  firewall-cmd --quiet --reload
fi

log "Checking http://127.0.0.1:$PORT/readyz"
for _ in $(seq 1 20); do
  if curl -fsS "http://127.0.0.1:$PORT/readyz"; then
    echo
    systemctl --no-pager --lines=0 status "$UNIT" || true
    log "Done."
    exit 0
  fi
  sleep 0.5
done

echo "readyz did not answer 200. Last logs:" >&2
curl -sS "http://127.0.0.1:$PORT/readyz" >&2 || true
echo >&2
journalctl --no-pager -n 30 -u "$UNIT" >&2
exit 1
