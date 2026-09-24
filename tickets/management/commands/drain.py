"""
Drain the Valkey order stream into Postgres in batches.

Runs as its own process, never inside a web worker. gunicorn forks N
workers; a loop started in a worker would become N duplicate consumers all
claiming the same entries.
"""
import time
import uuid
from datetime import datetime

import redis
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection
from django.db.utils import IntegrityError

from tickets.redis_client import client

COLUMNS = "order_id, event_id, user_id, status, created_at"

# Fallback path only. COPY cannot express ON CONFLICT, so when a redelivered
# batch collides with rows already in the table we retry row by row.
INSERT_SQL = (
    "INSERT INTO orders (order_id, event_id, user_id, status, created_at) "
    "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (order_id) DO NOTHING"
)

RECLAIM_EVERY = 30.0      # seconds between XAUTOCLAIM sweeps
RECLAIM_IDLE_MS = 60_000  # only steal entries abandoned this long


class Command(BaseCommand):
    help = "Move orders from the Valkey stream into Postgres in batches."

    def add_arguments(self, parser):
        parser.add_argument("--worker-id", default="drain-1")
        parser.add_argument("--batch-size", type=int, default=settings.BATCH_SIZE)

    def handle(self, *args, **opts):
        worker_id = opts["worker_id"]
        batch_size = opts["batch_size"]

        self._ensure_group()
        self.stderr.write(f"{worker_id} draining {settings.STREAM_KEY}\n")

        reclaim_cursor = "0-0"
        next_reclaim = time.monotonic() + RECLAIM_EVERY

        while True:
            # Single-threaded loop, so the reclaim sweep is folded in here
            # rather than run on a thread. block=200 guarantees we get back
            # here at least five times a second.
            if time.monotonic() >= next_reclaim:
                reclaim_cursor = self._reclaim(worker_id, reclaim_cursor, batch_size)
                next_reclaim = time.monotonic() + RECLAIM_EVERY

            try:
                resp = client.xreadgroup(
                    settings.CONSUMER_GROUP,
                    worker_id,
                    {settings.STREAM_KEY: ">"},
                    count=batch_size,
                    block=200,
                )
            except redis.RedisError as exc:
                self.stderr.write(f"read error: {exc}\n")
                time.sleep(0.5)
                continue

            if not resp:
                continue

            for _stream, entries in resp:
                ids, rows = self._to_rows(entries)
                self._flush(ids, rows)

    # ------------------------------------------------------------ helpers

    def _ensure_group(self):
        try:
            client.xgroup_create(
                settings.STREAM_KEY, settings.CONSUMER_GROUP, id="0", mkstream=True
            )
        except redis.ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    @staticmethod
    def _to_rows(entries):
        ids, rows = [], []
        for entry_id, fields in entries:
            ids.append(entry_id)
            rows.append(
                (
                    uuid.UUID(fields["order_id"]),
                    fields["event_id"],
                    fields.get("user_id"),
                    "confirmed",
                    datetime.fromisoformat(fields["ts"]),
                )
            )
        return ids, rows

    def _flush(self, ids, rows):
        if not rows:
            return

        # One COPY per batch instead of one INSERT per row. 1000 rows become
        # a single transaction and a single WAL flush; row-at-a-time would
        # need 1000 commits and wall at roughly 2,000 a second.
        try:
            with connection.cursor() as cur:
                with cur.copy(f"COPY orders ({COLUMNS}) FROM STDIN") as copy:
                    for row in rows:
                        copy.write_row(row)
        except IntegrityError:
            with connection.cursor() as cur:
                cur.executemany(INSERT_SQL, rows)
        except Exception as exc:
            # Leave the entries unacked so another sweep picks them up.
            self.stderr.write(f"flush error, batch left pending: {exc}\n")
            connection.close()
            return

        # Only now. Until XACK lands, Valkey keeps these entries pending,
        # which is what makes a crash mid-batch recoverable.
        client.xack(settings.STREAM_KEY, settings.CONSUMER_GROUP, *ids)

    def _reclaim(self, worker_id, cursor, batch_size):
        """Pick up entries a dead worker claimed and never acked."""
        try:
            cursor, entries, _ = client.xautoclaim(
                settings.STREAM_KEY,
                settings.CONSUMER_GROUP,
                worker_id,
                min_idle_time=RECLAIM_IDLE_MS,
                start_id=cursor,
                count=batch_size,
            )
        except redis.RedisError as exc:
            self.stderr.write(f"reclaim error: {exc}\n")
            return cursor

        if entries:
            ids, rows = self._to_rows(entries)
            self.stderr.write(f"reclaimed {len(ids)} entries\n")
            self._flush(ids, rows)

        return cursor
