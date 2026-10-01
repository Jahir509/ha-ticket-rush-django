# Run by hand

| File | What it is |
|---|---|
| `gunicorn.conf.py` | All gunicorn settings. Edit `BIND`, `WORKERS`, `PROMETHEUS_DIR` at the top. |
| `start.sh` | Starts gunicorn with that config. |
| `sync.sh` | Clean resync of the repo into `/opt/ha-ticket-rush-django`. Keeps `.env` and `.venv`. `--dry-run` to preview. |
| `prometheus.yml` | Scrape job to paste into Prometheus. |
| `ticketrush-dj-gunicorn.service`, `install_service.sh` | Run it as a systemd service. See [SERVICE.md](SERVICE.md). |

## Commands

```bash
manual/sync.sh --dry-run                         # preview sync to /opt
manual/sync.sh                                   # sync to /opt
manual/start.sh                                  # start (foreground)
curl -i http://127.0.0.1:8001/readyz             # 200 = up and Valkey reachable
curl -s http://127.0.0.1:8001/metrics | head     # metrics
sudo firewall-cmd --add-port=8001/tcp --permanent && sudo firewall-cmd --reload   # let Prometheus in
```

## Why Prometheus showed no data

1. **Nothing listened on port 8001.** The default config binds a unix
   socket (`/run/ticketrush-dj/gunicorn.sock`), so `10.2.116.112:8001` had
   nothing to scrape. This config binds `0.0.0.0:8001`.
2. **`PROMETHEUS_MULTIPROC_DIR` was never set.** Each of the 17 workers kept
   its own counters, so `/metrics` showed one random worker, and the
   `child_exit` hook crashed on shutdown. This config sets it.
3. **Wrong target format.** `targets: ['https://…']` is invalid; use
   `host:port` plus `scheme: https`.
4. **Prometheus read a different file.** The running container mounts
   `~/git/ha-ticket-rush/monitoring/prometheus.yml`, not the one in this repo.
   Check with
   `docker inspect ticketrush-prometheus --format '{{range .Mounts}}{{.Source}}{{"\n"}}{{end}}'`.
5. **`/readyz` 503** means Valkey is unreachable with `REDIS_URL` in `.env`.
   Test: `redis-cli -u "$REDIS_URL" ping`.
