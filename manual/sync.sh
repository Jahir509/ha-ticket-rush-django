#!/usr/bin/env bash
# Clean resync of this checkout into /opt/ha-ticket-rush-django.
#
#   manual/sync.sh               # sync
#   manual/sync.sh --dry-run     # show what would change, touch nothing
#
# --delete makes /opt an exact copy: files removed from the repo are removed
# there too. .env, .venv and the excluded paths below are never copied and
# never deleted, so the server's config and virtualenv survive every sync.
# Extra arguments are passed straight to rsync.
set -euo pipefail

DEST=${DEST:-/opt/ha-ticket-rush-django}
SRC=$(cd "$(dirname "$0")/.." && pwd)

if [ "$SRC" = "$DEST" ]; then
  echo "Run this from a checkout, not from $DEST itself." >&2
  exit 1
fi

sudo mkdir -p "$DEST"
sudo rsync -rlpt --delete --itemize-changes --chown=root:root \
  --exclude='.git/' \
  --exclude='.venv/' \
  --exclude='venv/' \
  --exclude='.env' \
  --exclude='__pycache__/' \
  --exclude='*.py[cod]' \
  --exclude='.vscode/' \
  --exclude='.idea/' \
  --exclude='*.log' \
  --exclude='staticfiles/' \
  --exclude='media/' \
  "$@" \
  "$SRC/" "$DEST/"

echo "Synced $SRC -> $DEST"
