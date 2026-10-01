# Deploy

What each file does, and how to run the app as systemd services on Rocky
Linux 10. For running it by hand on a dev machine, see [run.md](run.md).

## How it fits together

```
client ──> gunicorn (ticketrush-dj-web) ──> Valkey ──> drain (ticketrush-dj-drain@1) ──> Postgres
```

A purchase only touches Valkey: one Lua script takes a ticket and appends
the order to a stream. The drain service reads that stream and writes the
orders into Postgres in batches. Web requests never touch Postgres.

## What each file does

### App

| File | Purpose |
|---|---|
| `manage.py` | Django command line. Used for `migrate` and `drain`. |
| `ticketrush/settings.py` | All configuration, read from environment variables (the `.env` file). Postgres, Valkey, stream name, batch size. |
| `ticketrush/urls.py` | Maps URLs to views. |
| `ticketrush/wsgi.py` | The WSGI app that gunicorn loads. |
| `tickets/views.py` | The HTTP endpoints: `POST /events`, `GET /events/<id>`, `GET /events/<id>/stats`, `POST /events/<id>/purchase`, `GET /healthz`, `GET /readyz`, `GET /info`. |
| `tickets/redis_client.py` | One Valkey connection pool per worker, plus the Lua purchase script (take a ticket and queue the order in one atomic step). |
| `tickets/models.py` | The `orders` table. Only the drain writes to it. |
| `tickets/migrations/0001_initial.py` | Creates the `orders` table. |
| `tickets/management/commands/drain.py` | `manage.py drain`: reads orders from the Valkey stream, `COPY`s them into Postgres in batches, and acks them only after the write succeeds. |
| `tickets/apps.py`, `__init__.py` files | Django boilerplate. |

### Config

| File | Purpose |
|---|---|
| `requirements.txt` | Python packages: Django, gunicorn, psycopg, redis. |
| `.env.example` | Template for `.env`. Copy it and change the values. |
| `.env` | Your real settings. Not in git. |
| `gunicorn.conf.py` | gunicorn settings: sync workers, `WORKERS` count, listens on `unix:/run/ticketrush-dj/gunicorn.sock` unless `BIND` is set. |

### Scripts and services

| File | Purpose |
|---|---|
| `scripts/create_pgdb.sh` | Creates the Postgres role and database named in `.env`. Safe to re-run. |
| `scripts/deploy.sh` | Copies the checkout to `/opt/ha-ticket-rush-django`, installs dependencies, migrates, installs and restarts the services. Safe to re-run. |
| `scripts/deploy_only_web.sh` | Same as `deploy.sh`, but installs and runs only the web service (gunicorn). Stops and disables any drain instance on the host. |
| `deploy/systemd/ticketrush-dj-web.service` | systemd unit for gunicorn (the web server). |
| `deploy/systemd/ticketrush-dj-drain@.service` | systemd unit template for the drain. `@1` runs worker `drain-1`, `@2` runs `drain-2`, and so on. |
| `run.md` | Running everything by hand for development. |

## Set up on Rocky Linux 10

### 1. Install Postgres and Valkey

```bash
sudo dnf install -y git rsync python3 postgresql-server valkey
sudo postgresql-setup --initdb
sudo systemctl enable --now postgresql valkey
```

The app connects to Postgres over `127.0.0.1` with a password. Rocky's
default `pg_hba.conf` uses `ident` for that, which rejects the login. In
`/var/lib/pgsql/data/pg_hba.conf`, change the `host ... 127.0.0.1/32` and
`::1/128` lines from `ident` to `scram-sha-256`, then:

```bash
sudo systemctl restart postgresql
```

Skip this step if Postgres and Valkey run on other hosts. Point `PG_HOST`
and `REDIS_URL` in `.env` at them instead.

### 2. Get the code and configure it

```bash
git clone <repo-url> ~/ha-ticket-rush-django
cd ~/ha-ticket-rush-django
cp .env.example .env
vi .env    # passwords, WORKERS, and add SECRET_KEY=<something random>
```

### 3. Create the database

```bash
scripts/create_pgdb.sh
```

### 4. Deploy

```bash
scripts/deploy.sh
```

It asks for sudo, then:

1. creates the `ticketrush` system user
2. copies the checkout into `/opt/ha-ticket-rush-django` (removing files
   that were deleted from the repo, but keeping `.env` and `.venv`)
3. on the first run only, copies your `.env` to
   `/opt/ha-ticket-rush-django/.env`
4. creates the venv, installs `requirements.txt`, runs `migrate`
5. installs both units into `/etc/systemd/system`, enables them, restarts
   them, and checks `/readyz`

From now on, the file the services read is
`/opt/ha-ticket-rush-django/.env`. Edit that one, not the checkout's.

### 5. Check it works

```bash
curl --unix-socket /run/ticketrush-dj/gunicorn.sock http://localhost/readyz
```

## Day to day

| Task | Command |
|---|---|
| Deploy new code | `git pull && scripts/deploy.sh` |
| Status | `systemctl status ticketrush-dj-web 'ticketrush-dj-drain@*'` |
| Follow logs | `journalctl -fu ticketrush-dj-web -u 'ticketrush-dj-drain@*'` |
| Restart | `sudo systemctl restart ticketrush-dj-web 'ticketrush-dj-drain@*'` |
| Stop | `sudo systemctl stop ticketrush-dj-web 'ticketrush-dj-drain@*'` |
| Add a drain worker | `sudo systemctl enable --now ticketrush-dj-drain@2` |
| Remove it again | `sudo systemctl disable --now ticketrush-dj-drain@2` |
| Change settings | edit `/opt/ha-ticket-rush-django/.env`, then restart |

## Reaching it from other machines

gunicorn only listens on a local unix socket. To expose it directly, add
this to `/opt/ha-ticket-rush-django/.env`:

```
BIND=0.0.0.0:8001
```

then open the port and restart:

```bash
sudo firewall-cmd --add-port=8001/tcp --permanent
sudo firewall-cmd --reload
sudo systemctl restart ticketrush-dj-web
```

Putting nginx in front of the socket also works, but SELinux blocks nginx
from connecting to it by default and needs a policy change that is not
covered here.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `/readyz` returns 503 `valkey unavailable` | Valkey is down or `REDIS_URL` is wrong. |
| Drain logs `password authentication failed` or `Ident authentication failed` | `.env` password does not match, or `pg_hba.conf` still says `ident` (step 1). |
| Service fails with `status=203/EXEC` or `Permission denied` | SELinux. Check `sudo ausearch -m avc -ts recent` and run `sudo restorecon -R /opt/ha-ticket-rush-django`. |
| `deploy.sh` stops at "Running migrations" | Postgres is not reachable with the `.env` settings. Run `scripts/create_pgdb.sh` first. |
