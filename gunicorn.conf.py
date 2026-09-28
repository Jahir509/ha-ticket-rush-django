"""
gunicorn config for the sync-Django twin.

Three settings here decide whether the comparison with the async twin is
fair or meaningless: worker_class, preload_app and bind. Read the comments
before changing any of them.
"""
import multiprocessing
import os

# A unix socket, not 127.0.0.1:8001. This matters more than it looks: the
# sync worker does NOT support keep-alive and closes every connection after
# the response, so over TCP that would be one new connection per request.
# At 9,000 rps each closed socket sits 60s in TIME_WAIT, which needs 540,000
# ports out of the ~55,000 that exist. A unix socket has no ports at all, so
# the problem simply does not arise.
bind = os.environ.get("BIND", "unix:/run/ticketrush-dj/gunicorn.sock")

# Sync workers are processes that each serve one request at a time, so
# concurrency IS worker count. Little's Law: concurrency = rps x latency,
# and at 9,000 rps with 1.5 ms responses that is ~14. gunicorn's classic
# 2*cores+1 gives 17 on this box. Start there, then measure: past the core
# count the extra processes only add context switching.
workers = int(os.environ.get("WORKERS", multiprocessing.cpu_count() * 2 + 1))

# The point of the experiment. gthread or gevent would make this a
# different test.
worker_class = "sync"

# False so each worker builds its own Valkey pool after fork. Preloading
# would share one set of sockets across every child and interleave replies
# into garbage.
preload_app = False

backlog = 8192
timeout = 30
graceful_timeout = 30

# No recycling. A worker restarting mid-test shows up as a latency spike
# that has nothing to do with the code under test.
max_requests = 0

# Writing a log line per request is enough disk I/O on its own to become
# the bottleneck at these rates.
accesslog = None
errorlog = "-"
loglevel = "warning"


# Append these to gunicorn.conf.py.
#
# Without child_exit, every worker that dies leaves its metric files behind
# forever. MultiProcessCollector keeps summing them, so counters only ever
# climb and a restart looks like a traffic spike. mark_process_dead cleans
# up the counter and histogram files of that pid.
 
def child_exit(server, worker):
    from prometheus_client import multiprocess
    multiprocess.mark_process_dead(worker.pid)
 
 
def on_starting(server):
    # Wipe stale files from a previous run. RuntimeDirectory already clears
    # /run on stop, but this also covers a crash-restart.
    import glob
    import os
 
    d = os.environ.get("PROMETHEUS_MULTIPROC_DIR")
    if d and os.path.isdir(d):
        for f in glob.glob(os.path.join(d, "*.db")):
            try:
                os.remove(f)
            except OSError:
                pass
 
