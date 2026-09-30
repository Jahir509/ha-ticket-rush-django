#!/usr/bin/env python3
"""Bulk-loads dummy users into the `users` table using PostgreSQL COPY.

Install:
    pip install "psycopg[binary]" faker python-dotenv

Examples:
    generate_dummy_data.py                                # 50M rows, config from ../backend/.env
    generate_dummy_data.py --total 1000000 --workers 12   # 1M rows, 12 workers
    generate_dummy_data.py --dsn postgres://user:pass@host:5432/db
"""

import argparse
import multiprocessing as mp
import os
import random
import signal
import sys
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import psycopg
from dotenv import load_dotenv
from faker import Faker

COLUMNS = ("id", "email", "first_name", "last_name", "created_at")
NAME_POOL_SIZE = 5_000  # names pre-generated per worker (Faker per-row is slow)

# --- per-worker globals (set in init_worker) ---------------------------------
_conn = None
_cfg = None
_counter = None
_stop = None
_first_names = None
_last_names = None


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Bulk-loads dummy users into the `users` table.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--dsn", default="",
                   help="PostgreSQL connection string (overrides DATABASE_URL and DB_* variables)")
    p.add_argument("--env-file", default=".env,../backend/.env",
                   help="comma-separated env files to read DB_* from; earlier files win, missing ones are skipped")
    p.add_argument("--total", type=int, default=50_000_000, help="number of rows to insert")
    p.add_argument("--start", type=int, default=0, help="first id to use; 0 means max(id)+1")
    p.add_argument("--workers", type=int, default=8, help="parallel COPY workers (processes)")
    p.add_argument("--batch", type=int, default=50_000, help="rows per COPY call")
    p.add_argument("--prefix", default="user", help="email local-part prefix")
    p.add_argument("--domain", default="loadtest.local", help="email domain")
    p.add_argument("--days-back", type=int, default=365,
                   help="spread created_at over this many days into the past")
    p.add_argument("--truncate", action="store_true",
                   help="DESTRUCTIVE: empty the users table before loading")
    p.add_argument("--no-reset-sequence", dest="reset_seq", action="store_false",
                   help="skip moving the id sequence past the inserted rows")
    return p.parse_args()


# --- helpers -----------------------------------------------------------------
def comma(n: int) -> str:
    return f"{n:,}"


def per_second(n: int, elapsed: float) -> int:
    return int(n / elapsed) if elapsed > 0 else 0


def redact(dsn: str) -> str:
    at = dsn.rfind("@")
    slashes = dsn.find("//")
    if at == -1 or slashes == -1 or slashes + 2 > at:
        return dsn
    credentials = dsn[slashes + 2:at]
    user, sep, _ = credentials.partition(":")
    if not sep:
        return dsn
    return dsn[:slashes + 2] + user + ":***" + dsn[at:]


def resolve_dsn(args: argparse.Namespace) -> str:
    if args.dsn:
        return args.dsn

    for path in args.env_file.split(","):
        path = path.strip()
        if not path or not os.path.exists(path):
            continue
        # override=False -> variables already set (i.e. from earlier files) win
        load_dotenv(path, override=False)

    if dsn := os.environ.get("DATABASE_URL"):
        return dsn

    def get(key: str, fallback: str) -> str:
        return os.environ.get(key) or fallback

    user = quote(get("PG_USER", ""), safe="")
    password = quote(get("PG_PASSWORD", ""), safe="")
    host = get("PG_HOST", "localhost")
    if ":" in host and not host.startswith("["):  # IPv6 literal
        host = f"[{host}]"
    port = get("PG_PORT", "5432")
    name = get("PG_NAME", "ticketrush_dj")
    return f"postgresql://{user}:{password}@{host}:{port}/{name}"


# --- worker ------------------------------------------------------------------
def init_worker(dsn, cfg, counter, stop):
    global _conn, _cfg, _counter, _stop, _first_names, _last_names

    # Let the parent handle Ctrl-C; workers finish their current batch and exit.
    signal.signal(signal.SIGINT, signal.SIG_IGN)

    _cfg, _counter, _stop = cfg, counter, stop
    _conn = psycopg.connect(dsn, autocommit=True)

    faker = Faker()
    Faker.seed(os.getpid() ^ int(time.time_ns()))
    _first_names = [faker.first_name() for _ in range(NAME_POOL_SIZE)]
    _last_names = [faker.last_name() for _ in range(NAME_POOL_SIZE)]


def load_batch(bounds):
    """COPY ids [lo, hi) into users. Returns the number of rows copied."""
    if _stop.is_set():
        return 0

    lo, hi = bounds
    cfg = _cfg
    max_age = cfg["days_back"] * 86_400
    now = datetime.now(timezone.utc)
    prefix, domain = cfg["prefix"], cfg["domain"]
    firsts, lasts = _first_names, _last_names
    choice, randrange = random.choice, random.randrange

    def rows():
        # tab-separated COPY text format, written in chunks
        buf = []
        for i in range(lo, hi):
            ts = now - timedelta(seconds=randrange(max_age))
            buf.append(
                f"{i}\t{prefix}{i}@{domain}\t{choice(firsts)}\t{choice(lasts)}\t{ts.isoformat()}\n"
            )
            if len(buf) >= 5_000:
                yield "".join(buf)
                buf.clear()
        if buf:
            yield "".join(buf)

    try:
        with _conn.cursor() as cur:
            with cur.copy(f"COPY users ({', '.join(COLUMNS)}) FROM STDIN") as copy:
                for chunk in rows():
                    copy.write(chunk)
    except Exception as e:
        raise RuntimeError(f"copy ids {lo}..{hi - 1}: {e}") from e

    n = hi - lo
    with _counter.get_lock():
        _counter.value += n
    return n


# --- main --------------------------------------------------------------------
def report_progress(n: int, total: int, began: float):
    elapsed = time.monotonic() - began
    rate = per_second(n, elapsed)
    eta = "--"
    if rate > 0 and n < total:
        eta = str(timedelta(seconds=round((total - n) / rate)))
    pct = n * 100 / total
    sys.stdout.write(
        f"\r  {comma(n)} / {comma(total)}  ({pct:5.1f}%)  {comma(rate)} rows/sec  eta {eta:<10}"
    )
    sys.stdout.flush()


def run(args: argparse.Namespace) -> None:
    if args.total <= 0:
        raise SystemExit("--total must be greater than 0")
    if args.workers <= 0:
        raise SystemExit("--workers must be greater than 0")
    if args.batch <= 0:
        raise SystemExit("--batch must be greater than 0")

    dsn = resolve_dsn(args)

    try:
        conn = psycopg.connect(dsn, autocommit=True)
    except Exception as e:
        raise RuntimeError(f"connect {redact(dsn)}: {e}") from e

    with conn:
        if args.truncate:
            print("truncating users ...")
            conn.execute("TRUNCATE TABLE users RESTART IDENTITY")

        start = args.start
        if start <= 0:
            start = conn.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM users").fetchone()[0]
        end = start + args.total

        print(f"target      : {redact(dsn)}")
        print(f"rows        : {comma(args.total)}")
        print(f"id range    : {comma(start)} .. {comma(end - 1)}")
        print(f"email       : {args.prefix}{start}@{args.domain} .. {args.prefix}{end - 1}@{args.domain}")
        print(f"workers     : {args.workers}, batch {comma(args.batch)}\n")

        cfg = {"prefix": args.prefix, "domain": args.domain, "days_back": args.days_back}
        counter = mp.Value("q", 0)
        stop = mp.Event()
        batches = [(lo, min(lo + args.batch, end)) for lo in range(start, end, args.batch)]

        began = time.monotonic()
        interrupted = False

        pool = mp.Pool(args.workers, init_worker, (dsn, cfg, counter, stop))
        try:
            results = pool.imap_unordered(load_batch, batches)
            while True:
                try:
                    results.next(timeout=2)
                except mp.TimeoutError:
                    pass
                except StopIteration:
                    break
                report_progress(counter.value, args.total, began)
        except KeyboardInterrupt:
            interrupted = True
            stop.set()  # remaining queued batches become no-ops
        except BaseException:
            stop.set()
            pool.terminate()
            print()
            raise
        finally:
            pool.close()
            pool.join()

        done = counter.value
        report_progress(done, args.total, began)
        print()

        if interrupted:
            raise RuntimeError("interrupted")

        elapsed = time.monotonic() - began
        print(f"\ninserted {comma(done)} rows in {timedelta(seconds=round(elapsed))} "
              f"({comma(per_second(done, elapsed))} rows/sec)")

        if args.reset_seq:
            conn.execute(
                """SELECT setval(
                       pg_get_serial_sequence('users', 'id'),
                       COALESCE((SELECT MAX(id) FROM users), 0) + 1,
                       false)"""
            )
            print("id sequence moved past the inserted rows")


def main() -> None:
    args = parse_args()
    try:
        run(args)
    except RuntimeError as e:
        print(f"\nerror: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()