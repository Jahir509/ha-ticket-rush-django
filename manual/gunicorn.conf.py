"""
Standalone gunicorn config. Everything you need to change is at the top.

Run from anywhere:
    .venv/bin/gunicorn -c manual/gunicorn.conf.py
"""
import glob
import os
from pathlib import Path

from dotenv import load_dotenv

# ---- Edit these -----------------------------------------------------------

BIND = "0.0.0.0:8001"   # TCP, so curl and Prometheus can reach it
WORKERS = 17            # sync workers; 2 * CPU cores + 1 is a good start
PROMETHEUS_DIR = "/tmp/ticketrush-dj-prometheus"   # metric files, one per worker

# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent

# Django settings read DB / Valkey config from the environment, so load the
# repo's .env before workers start. Values already in the environment win.
load_dotenv(ROOT / ".env")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ticketrush.settings")

# Without this, every worker keeps its own counters and /metrics shows only
# the one worker that answered the scrape. Must be set before any worker
# imports prometheus_client, which is why it is here and not in Django.
os.environ.setdefault("PROMETHEUS_MULTIPROC_DIR", PROMETHEUS_DIR)

chdir = str(ROOT)
wsgi_app = "ticketrush.wsgi"
bind = os.environ.get("BIND", BIND)
workers = int(os.environ.get("WORKERS", WORKERS))
worker_class = "sync"
preload_app = False     # each worker opens its own Valkey connections
backlog = 8192
timeout = 30
graceful_timeout = 30
max_requests = 0

accesslog = None
errorlog = "-"
loglevel = "info"

# gunicorn 26 control socket; default is $HOME/.gunicorn, which may not be
# writable for a service user.
control_socket = os.path.join(os.environ["PROMETHEUS_MULTIPROC_DIR"], "gunicorn.ctl")


def on_starting(server):
    # Create the metrics dir and remove files left from the previous run,
    # otherwise old counters get added to the new ones.
    d = os.environ["PROMETHEUS_MULTIPROC_DIR"]
    os.makedirs(d, exist_ok=True)
    for f in glob.glob(os.path.join(d, "*.db")):
        os.remove(f)


def child_exit(server, worker):
    # Remove the live gauge files of a worker that exited.
    from prometheus_client import multiprocess
    multiprocess.mark_process_dead(worker.pid)
