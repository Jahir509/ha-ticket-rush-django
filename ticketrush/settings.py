"""
Settings for the sync-Django twin of the FastAPI Ticket Rush API.

Tuned for a load test, not for a public site: DEBUG off, no access log, and
a middleware stack stripped to nothing because this API uses no sessions, no
auth and no CSRF. Set FULL_MIDDLEWARE=1 to put the stock stack back and
measure what it costs per request.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("SECRET_KEY", "load-test-only-never-in-production")
DEBUG = False
ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = ["tickets"]

if os.environ.get("FULL_MIDDLEWARE") == "1":
    INSTALLED_APPS += [
        "django.contrib.contenttypes",
        "django.contrib.auth",
        "django.contrib.sessions",
        "django.contrib.messages",
    ]
    MIDDLEWARE = [
        "django.middleware.security.SecurityMiddleware",
        "django.contrib.sessions.middleware.SessionMiddleware",
        "django.middleware.common.CommonMiddleware",
        "django.middleware.csrf.CsrfViewMiddleware",
        "django.contrib.auth.middleware.AuthenticationMiddleware",
        "django.contrib.messages.middleware.MessageMiddleware",
        "django.middleware.clickjacking.XFrameOptionsMiddleware",
    ]
else:
    MIDDLEWARE = []

ROOT_URLCONF = "ticketrush.urls"
WSGI_APPLICATION = "ticketrush.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": False,
        "OPTIONS": {"context_processors": []},
    }
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("PG_NAME", "ticketrush_dj"),
        "USER": os.environ.get("PG_USER", "ticketrush"),
        "PASSWORD": os.environ.get("PG_PASSWORD", "ticketrush"),
        "HOST": os.environ.get("PG_HOST", "127.0.0.1"),
        "PORT": os.environ.get("PG_PORT", "5432"),
        # Only the drain command touches Postgres. Web workers never do,
        # which is the whole point of the architecture.
        "CONN_MAX_AGE": 600,
        "OPTIONS": {"connect_timeout": 5},
    }
}

# --- Valkey / stream ------------------------------------------------------
REDIS_URL = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/1")

# A gunicorn sync worker serves exactly one request at a time, so one
# connection per process is enough. 4 is slack, not need. The async FastAPI
# twin needed 128 because a single process had hundreds of requests in
# flight at once.
REDIS_MAX_CONNECTIONS = int(os.environ.get("REDIS_MAX_CONNECTIONS", "4"))

STREAM_KEY = os.environ.get("STREAM_KEY", "orders_dj:stream")
CONSUMER_GROUP = os.environ.get("CONSUMER_GROUP", "pg")
BATCH_SIZE = int(os.environ.get("BATCH_SIZE", "1000"))
STREAM_MAXLEN = int(os.environ.get("STREAM_MAXLEN", "2000000"))

USE_TZ = True
TIME_ZONE = "UTC"
USE_I18N = False
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "WARNING"},
}
