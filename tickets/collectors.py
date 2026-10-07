"""
Scrape-time collectors for /metrics: the VM and Postgres, next to the
request metrics.

Everything here is computed when Prometheus asks, by whichever worker
answers the scrape, and is never stored, so it needs nothing from the
multiprocess machinery.

CPU is exported as cumulative seconds (counters), not percentages. A
percentage needs two samples taken some time apart; a counter is correct
from a single read, and rate() in PromQL turns it into cores in use.
"""
import os

import psutil
from django.db import connection, transaction
from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily


def _process_label(proc):
    """Group processes by what they are, not just by binary name."""
    cmd = " ".join(proc.info["cmdline"] or [])
    if not cmd:
        return "kernel"              # kernel threads have no command line
    if "gunicorn" in cmd:
        return "gunicorn"
    if "manage.py drain" in cmd:
        return "django-drain"
    if "app.drain" in cmd:
        return "fastapi-drain"
    if "uvicorn" in cmd:
        return "uvicorn"
    return proc.info["name"] or "unknown"


class SystemCollector:
    def collect(self):
        # ---------------------------------------------------------- CPU
        cpu = CounterMetricFamily(
            "vm_cpu_seconds", "CPU time in each mode, all cores summed.",
            labels=["mode"])
        for mode, seconds in psutil.cpu_times()._asdict().items():
            cpu.add_metric([mode], seconds)
        yield cpu

        yield GaugeMetricFamily("vm_cpu_count", "Logical CPUs.",
                                value=psutil.cpu_count())

        load = GaugeMetricFamily("vm_load_average", "Run-queue length.",
                                 labels=["period"])
        for period, value in zip(("1m", "5m", "15m"), os.getloadavg()):
            load.add_metric([period], value)
        yield load

        # ------------------------------------------------------- memory
        mem = psutil.virtual_memory()
        for field in ("total", "available", "used", "free", "buffers", "cached"):
            yield GaugeMetricFamily(f"vm_memory_{field}_bytes", f"Memory {field}.",
                                    value=getattr(mem, field, 0))
        yield GaugeMetricFamily("vm_swap_used_bytes", "Swap in use.",
                                value=psutil.swap_memory().used)

        # ------------------------------------------------------ storage
        total = GaugeMetricFamily("vm_disk_total_bytes", "Filesystem size.",
                                  labels=["mount"])
        used = GaugeMetricFamily("vm_disk_used_bytes", "Filesystem used.",
                                 labels=["mount"])
        for part in psutil.disk_partitions(all=False):
            try:
                usage = psutil.disk_usage(part.mountpoint)
            except OSError:
                continue
            total.add_metric([part.mountpoint], usage.total)
            used.add_metric([part.mountpoint], usage.used)
        yield total
        yield used

        io = psutil.disk_io_counters()
        if io:
            disk_io = CounterMetricFamily("vm_disk_io_bytes", "Bytes read and written.",
                                          labels=["direction"])
            disk_io.add_metric(["read"], io.read_bytes)
            disk_io.add_metric(["write"], io.write_bytes)
            yield disk_io

        # ------------------------------------------------------ network
        net = CounterMetricFamily("vm_network_bytes", "Bytes through each interface.",
                                  labels=["interface", "direction"])
        for nic, c in psutil.net_io_counters(pernic=True).items():
            if nic == "lo":
                continue
            net.add_metric([nic, "sent"], c.bytes_sent)
            net.add_metric([nic, "received"], c.bytes_recv)
        yield net

        # ---------------------------------------------------- processes
        # Summed per label. When a process exits its seconds leave the sum,
        # which rate() reads as a counter reset: expect a rare spike, not a
        # wrong steady value.
        cpu_by, mem_by, count_by = {}, {}, {}
        for proc in psutil.process_iter(["name", "cmdline", "cpu_times", "memory_info"]):
            times, rss = proc.info["cpu_times"], proc.info["memory_info"]
            if times is None or rss is None:
                continue
            label = _process_label(proc)
            cpu_by[label] = cpu_by.get(label, 0.0) + times.user + times.system
            mem_by[label] = mem_by.get(label, 0) + rss.rss
            count_by[label] = count_by.get(label, 0) + 1

        pcpu = CounterMetricFamily("vm_process_cpu_seconds",
                                   "CPU time of every process with this label.",
                                   labels=["name"])
        pmem = GaugeMetricFamily("vm_process_memory_bytes",
                                 "Resident memory of every process with this label.",
                                 labels=["name"])
        pcount = GaugeMetricFamily("vm_process_count", "Processes with this label.",
                                   labels=["name"])
        for label in cpu_by:
            pcpu.add_metric([label], cpu_by[label])
            pmem.add_metric([label], mem_by[label])
            pcount.add_metric([label], count_by[label])
        yield pcpu
        yield pmem
        yield pcount

        yield GaugeMetricFamily("vm_boot_time_seconds", "Boot time, unix seconds.",
                                value=psutil.boot_time())


DB_COUNTERS = ("xact_commit", "xact_rollback", "blks_read", "blks_hit",
               "tup_returned", "tup_fetched", "tup_inserted", "tup_updated",
               "tup_deleted", "deadlocks", "temp_files", "temp_bytes", "conflicts")


class PostgresCollector:
    """Postgres stats through the worker's own Django connection."""

    def collect(self):
        up = GaugeMetricFamily("db_up", "1 if the stats queries succeeded.")
        try:
            families = list(self._collect())
        except Exception:
            up.add_metric([], 0)
            yield up
            return
        up.add_metric([], 1)
        yield up
        yield from families

    def _collect(self):
        with transaction.atomic(), connection.cursor() as cur:
            # Never let a slow stats query hold a worker.
            cur.execute("SET LOCAL statement_timeout = 2000")

            cur.execute("""
                SELECT coalesce(usename, '-'), coalesce(state, 'unknown'), count(*)
                FROM pg_stat_activity
                WHERE datname = current_database()
                  AND backend_type = 'client backend'
                  AND pid <> pg_backend_pid()
                GROUP BY 1, 2""")
            conns = GaugeMetricFamily("db_connections",
                                      "Connections to this database by user and state.",
                                      labels=["user", "state"])
            for user, state, n in cur.fetchall():
                conns.add_metric([user, state], n)
            yield conns

            cur.execute("SELECT setting::int FROM pg_settings WHERE name = 'max_connections'")
            yield GaugeMetricFamily("db_max_connections", "Server connection limit.",
                                    value=cur.fetchone()[0])

            cur.execute("SELECT count(*) FROM pg_stat_activity "
                        "WHERE backend_type = 'client backend'")
            yield GaugeMetricFamily("db_connections_all_databases",
                                    "Client connections on the whole server.",
                                    value=cur.fetchone()[0])

            cur.execute(f"SELECT {', '.join(DB_COUNTERS)} FROM pg_stat_database "
                        "WHERE datname = current_database()")
            for name, value in zip(DB_COUNTERS, cur.fetchone()):
                yield CounterMetricFamily(f"db_{name}", f"pg_stat_database.{name}",
                                          value=float(value or 0))

            cur.execute("SELECT pg_database_size(current_database())")
            yield GaugeMetricFamily("db_size_bytes", "Database size on disk.",
                                    value=cur.fetchone()[0])

            cur.execute("""
                SELECT coalesce(max(extract(epoch FROM now() - query_start)), 0),
                       count(*) FILTER (WHERE wait_event_type = 'Lock')
                FROM pg_stat_activity
                WHERE datname = current_database() AND state = 'active'
                  AND pid <> pg_backend_pid()""")
            longest, lock_waits = cur.fetchone()
            yield GaugeMetricFamily("db_longest_query_seconds",
                                    "Age of the oldest running query.", value=float(longest))
            yield GaugeMetricFamily("db_lock_waits", "Queries waiting on a lock.",
                                    value=lock_waits)

            cur.execute("""
                SELECT relname, seq_scan, coalesce(idx_scan, 0), n_live_tup, n_dead_tup
                FROM pg_stat_user_tables""")
            seq = CounterMetricFamily("db_table_seq_scans", "Full table scans.",
                                      labels=["table"])
            idx = CounterMetricFamily("db_table_index_scans", "Index scans.",
                                      labels=["table"])
            live = GaugeMetricFamily("db_table_rows", "Estimated live rows.",
                                     labels=["table"])
            dead = GaugeMetricFamily("db_table_dead_rows", "Rows waiting for vacuum.",
                                     labels=["table"])
            for rel, s, i, n_live, n_dead in cur.fetchall():
                seq.add_metric([rel], s)
                idx.add_metric([rel], i)
                live.add_metric([rel], n_live)
                dead.add_metric([rel], n_dead)
            yield seq
            yield idx
            yield live
            yield dead