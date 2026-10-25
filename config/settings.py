"""
Django settings for Carverse Check.

Everything that differs between your laptop and the live site comes from environment
variables. Locally they are read from the .env file (never committed); on Render they are
set in the dashboard. See .env.example for the full list.
"""

import os
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def env_list(name, default=""):
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


# --- Core -------------------------------------------------------------------------------

# Off unless DJANGO_DEBUG=1 is set, so a missing setting can never expose debug pages.
DEBUG = os.environ.get("DJANGO_DEBUG", "0") == "1"

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = "dev-only-insecure-key-never-used-in-production"
    else:
        raise RuntimeError("DJANGO_SECRET_KEY must be set when DJANGO_DEBUG is not 1.")

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "whitenoise.runserver_nostatic",   # local server: let WhiteNoise serve CSS/JS so the browser always gets the latest version
    "django.contrib.staticfiles",
    "checker",
]

MIDDLEWARE = [
    "checker.middleware.HealthCheckMiddleware",     # answers /healthz first (see the class for why)
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",   # serves CSS/JS on Render
    # Compresses pages (CSS/JS are already compressed by WhiteNoise). The public pages hold
    # no secrets, and Django masks CSRF tokens differently on every response (the admin
    # login), which is Django's defence against the BREACH compression attack.
    "django.middleware.gzip.GZipMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


# --- Database ---------------------------------------------------------------------------
# DATABASE_URL (Neon Postgres) on the live site; SQLite on your laptop when it isn't set.

DATABASES = {
    "default": dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=600,
        conn_health_checks=True,
    )
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-gb"
TIME_ZONE = "Europe/London"
USE_I18N = True
USE_TZ = True


# --- Static files -----------------------------------------------------------------------

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    # Live site: compressed files with content hashes in their names, so browsers can cache
    # them for a long time (needs collectstatic, which Render's build runs). Locally and in
    # tests: plain files, no build step needed.
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage" if DEBUG
                    else "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Django's default cache: each server process's own memory. DVSA's answers and the rate-limit
# counts live here, which keeps the privacy notice's promise that plates are only held in
# memory, never written to a database.
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}


# --- Logging and error emails -----------------------------------------------------------
# Everything goes to the console, which is what Render's log page shows. Unexpected errors
# (500s) are also emailed when DJANGO_ADMIN_EMAIL and the EMAIL_* settings are set.
# "DVSA is down" pages (503) are logged but not emailed, to avoid a flood of identical emails.

LOG_LEVEL = os.environ.get("DJANGO_LOG_LEVEL", "INFO")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "require_debug_false": {"()": "django.utils.log.RequireDebugFalse"},
        "skip_unavailable": {
            "()": "django.utils.log.CallbackFilter",
            "callback": lambda record: getattr(record, "status_code", None) != 503,
        },
    },
    "formatters": {
        "plain": {"format": "{levelname} {name}: {message}", "style": "{"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "plain"},
        "mail_admins": {
            "class": "django.utils.log.AdminEmailHandler",
            "level": "ERROR",
            "filters": ["require_debug_false", "skip_unavailable"],
        },
        "null": {"class": "logging.NullHandler"},
    },
    "loggers": {
        "django": {"handlers": ["console", "mail_admins"], "level": "ERROR", "propagate": False},
        # Bots constantly send requests for other sites' host names. Django rejects them;
        # logging each one would bury the real problems.
        "django.security.DisallowedHost": {"handlers": ["null"], "propagate": False},
        "checker": {"handlers": ["console"], "level": LOG_LEVEL, "propagate": False},
    },
}

ADMIN_EMAIL = os.environ.get("DJANGO_ADMIN_EMAIL", "")
EMAIL_HOST = os.environ.get("EMAIL_HOST", "")
if ADMIN_EMAIL and EMAIL_HOST:
    ADMINS = [ADMIN_EMAIL]
    EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
    EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
    EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
    EMAIL_USE_TLS = True
    EMAIL_TIMEOUT = 10
    SERVER_EMAIL = os.environ.get("EMAIL_FROM", EMAIL_HOST_USER)
    EMAIL_SUBJECT_PREFIX = "[Carverse Check] "


# --- Security on the live site ----------------------------------------------------------
# Render terminates HTTPS and tells Django through the X-Forwarded-Proto header.

if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    # On unless DJANGO_SECURE_SSL_REDIRECT=0: CI's Lighthouse job runs production settings
    # over plain http on its own machine, where there's no HTTPS to redirect to.
    SECURE_SSL_REDIRECT = os.environ.get("DJANGO_SECURE_SSL_REDIRECT", "1") == "1"
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_CONTENT_TYPE_NOSNIFF = True

# HSTS preload needs a domain we own and submit to the browsers' list; a *.onrender.com
# address can't be preloaded, so that one deployment-check warning is switched off on purpose.
SILENCED_SYSTEM_CHECKS = ["security.W021"]


# --- Project settings -------------------------------------------------------------------

# The DuckDB warehouse that load_mot_marts reads (only needed where the pipeline runs).
MOT_WAREHOUSE_PATH = os.environ.get("MOT_WAREHOUSE", str(BASE_DIR / "data" / "warehouse" / "mot.duckdb"))

# DVSA MOT history API credentials. Live lookups are off when these are empty.
DVSA_CLIENT_ID = os.environ.get("DVSA_CLIENT_ID", "")
DVSA_CLIENT_SECRET = os.environ.get("DVSA_CLIENT_SECRET", "")
DVSA_API_KEY = os.environ.get("DVSA_API_KEY", "")
DVSA_SCOPE = os.environ.get("DVSA_SCOPE", "")
DVSA_TOKEN_URL = os.environ.get("DVSA_TOKEN_URL", "")

# Limits that protect the DVSA quota (see checker/ratelimit.py). Keep the site-wide one
# below the request rate in DVSA's approval email.
PLATE_LOOKUPS_PER_MINUTE = int(os.environ.get("PLATE_LOOKUPS_PER_MINUTE", "20"))
DVSA_CALLS_PER_MINUTE = int(os.environ.get("DVSA_CALLS_PER_MINUTE", "300"))
