# Run

## 1. Create the Postgres database

The values below match `.env.example`. Change them if your `.env` differs.

```bash
sudo -u postgres psql -c "CREATE ROLE ticketrush LOGIN PASSWORD 'ticketrush';"
sudo -u postgres psql -c "CREATE DATABASE ticketrush_dj OWNER ticketrush;"
```

If the role already exists, reset its password instead:

```bash
sudo -u postgres psql -c "ALTER ROLE ticketrush PASSWORD 'ticketrush';"
```

Check it works:

```bash
psql -h 127.0.0.1 -U ticketrush -d ticketrush_dj -c 'select 1;'
```

## 2. Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

## 3. Load env and migrate

`settings.py` does not read `.env` itself, so export it in every terminal:

```bash
set -a; source .env; set +a
python manage.py migrate
```

## 4. Run

Valkey/Redis must be running on `127.0.0.1:6379`.

Terminal 1, the web server:

```bash
source .venv/bin/activate
set -a; source .env; set +a
BIND=127.0.0.1:8001 gunicorn -c gunicorn.conf.py ticketrush.wsgi
```

Terminal 2, the drain (moves orders from Valkey into Postgres):

```bash
source .venv/bin/activate
set -a; source .env; set +a
python manage.py drain --worker-id drain-1
```

## 5. Test

```bash
curl -s localhost:8001/readyz
curl -s -X POST localhost:8001/events -H 'content-type: application/json' \
  -d '{"name":"demo","total_tickets":100}'
# use the event_id from the response:
curl -s -X POST "localhost:8001/events/<event_id>/purchase?user_id=u1"
curl -s localhost:8001/events/<event_id>/stats
```

## 6. Deploy on the server (Rocky 10)

Postgres (step 1) and Valkey must already be running. From a checkout on
the server:

```bash
git pull
scripts/deploy.sh
```

It syncs the checkout into `/opt/ha-ticket-rush-django`, sets up the venv,
runs migrations and restarts two systemd services:

- `ticketrush-dj-web` runs gunicorn on `unix:/run/ticketrush-dj/gunicorn.sock`
- `ticketrush-dj-drain@1` runs the drain as `drain-1`

On the first run it creates `/opt/ha-ticket-rush-django/.env` from `.env`
(or `.env.example`). Later runs leave that file alone, so edit it there.
To listen on TCP instead of the socket, add `BIND=0.0.0.0:8001` to it and
open the port with `firewall-cmd --add-port=8001/tcp --permanent && firewall-cmd --reload`.

```bash
systemctl status ticketrush-dj-web 'ticketrush-dj-drain@*'
journalctl -fu ticketrush-dj-web -u 'ticketrush-dj-drain@*'
curl --unix-socket /run/ticketrush-dj/gunicorn.sock http://localhost/readyz
systemctl enable --now ticketrush-dj-drain@2   # a second drain worker
```
