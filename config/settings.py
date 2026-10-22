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
    "django.contrib.staticfiles",
    "checker",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",   # serves CSS/JS on Render
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


# --- Security on the live site ----------------------------------------------------------
# Render terminates HTTPS and tells Django through the X-Forwarded-Proto header.

if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = True
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
