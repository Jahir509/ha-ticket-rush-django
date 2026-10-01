# gunicorn as a systemd service

Runs the Django app at boot as `ticketrush-dj-gunicorn.service`, listening
on `0.0.0.0:8001`, using `manual/gunicorn.conf.py`.

| File | What it is |
|---|---|
| `ticketrush-dj-gunicorn.service` | The systemd unit (template). |
| `install_service.sh` | Installs everything and starts the service. |

## First install

On the server, in a checkout of this repo:

```bash
# 1. Config: DB and Valkey settings
sudo mkdir -p /opt/ha-ticket-rush-django
sudo cp .env /opt/ha-ticket-rush-django/.env      # or .env.example, then edit

# 2. Install and start
manual/install_service.sh
```

`install_service.sh` does, in order:

1. syncs the repo to `/opt/ha-ticket-rush-django` (`manual/sync.sh`)
2. creates the `ticketrush` system user
3. sets `.env` to `root:ticketrush 640` (readable by the service only)
4. creates `/opt/ha-ticket-rush-django/.venv` and installs `requirements.txt`
5. runs `manage.py migrate`
6. copies the unit to `/etc/systemd/system/`, enables and restarts it
7. disables `ticketrush-dj-web.service` from `deploy.sh`, if present
8. opens port 8001 in firewalld
9. waits for `/readyz` to return 200

It ends with `Done.` or prints the service log.

## Update code

```bash
git pull
manual/install_service.sh
```

## Day to day

```bash
sudo systemctl status  ticketrush-dj-gunicorn
sudo systemctl restart ticketrush-dj-gunicorn
sudo systemctl reload  ticketrush-dj-gunicorn     # graceful: new workers, no dropped requests
sudo systemctl stop    ticketrush-dj-gunicorn
sudo journalctl -u ticketrush-dj-gunicorn -f      # live logs

curl -i http://127.0.0.1:8001/readyz
curl -s http://127.0.0.1:8001/metrics | head
```

## Changing settings

| Change | Where | Then |
|---|---|---|
| Port, worker count | `BIND`, `WORKERS` at the top of `manual/gunicorn.conf.py` | `manual/install_service.sh` |
| DB, Valkey | `/opt/ha-ticket-rush-django/.env` | `sudo systemctl restart ticketrush-dj-gunicorn` |
| One value without editing files | `sudo systemctl edit ticketrush-dj-gunicorn`, add `[Service]` and `Environment=WORKERS=8` | `sudo systemctl restart ticketrush-dj-gunicorn` |

## Where things are

| What | Path |
|---|---|
| Code | `/opt/ha-ticket-rush-django` |
| Config | `/opt/ha-ticket-rush-django/.env` |
| Unit | `/etc/systemd/system/ticketrush-dj-gunicorn.service` |
| Prometheus metric files | `/run/ticketrush-dj/prometheus` |
| gunicorn control socket | `/run/ticketrush-dj/prometheus/gunicorn.ctl` |

## Troubleshooting

| Symptom | Cause |
|---|---|
| `/readyz` returns 503 | Valkey not reachable with `REDIS_URL` in `.env`. Test: `redis-cli -u "<REDIS_URL>" ping` |
| Stops at "Migrations" | Postgres not reachable with the `PG_*` values in `.env`. |
| `Address already in use` | Something else holds 8001: `sudo ss -lntp \| grep 8001` |
| Prometheus target down | Port 8001 closed: `sudo firewall-cmd --list-ports` |
| `status=203/EXEC` | `.venv` missing. Run `manual/install_service.sh` again. |

## Remove

```bash
sudo systemctl disable --now ticketrush-dj-gunicorn
sudo rm /etc/systemd/system/ticketrush-dj-gunicorn.service
sudo systemctl daemon-reload
```
