"""Settings shared by every environment.

All secrets and machine-specific values come from environment variables
(or a .env file at the repository root). See .env.example for every key.
"""

from decimal import Decimal
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parents[2]

env = environ.Env(DEBUG=(bool, False))
environ.Env.read_env(BASE_DIR / ".env")

# --- Core ---------------------------------------------------------------------

SECRET_KEY = env("SECRET_KEY")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
    # third party
    "django_htmx",
    "django_q",
    # local
    "apps.core",
    "apps.users",
    "apps.catalog",
    "apps.suppliers",
    "apps.importer",
    "apps.ai",
    "apps.inquiries",
    "apps.sources",
    "apps.archive",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.auth.middleware.LoginRequiredMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.suppliers.context_processors.cost_visibility",
            ],
        },
    },
]

# --- Database -----------------------------------------------------------------
# Empty or missing DATABASE_URL falls back to SQLite so the project runs without
# docker. PostgreSQL-only features (pg_trgm) degrade gracefully on SQLite.

DATABASE_URL = env("DATABASE_URL", default="") or f"sqlite:///{BASE_DIR / 'db.sqlite3'}"
DATABASES = {"default": env.db_url_config(DATABASE_URL)}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Auth ---------------------------------------------------------------------

AUTH_USER_MODEL = "users.User"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "core:home"
LOGOUT_REDIRECT_URL = "login"

# --- I18N ---------------------------------------------------------------------

LANGUAGE_CODE = "zh-hans"
TIME_ZONE = "Asia/Shanghai"
USE_I18N = True
USE_TZ = True

# --- Static & media -----------------------------------------------------------

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DATA_UPLOAD_MAX_MEMORY_SIZE = 20 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 20 * 1024 * 1024

# --- Background tasks (django-q2, ORM broker: task table lives in the DB) ------

Q_CLUSTER = {
    "name": "tpdc",
    "orm": "default",
    "workers": 2,
    "timeout": 300,
    "retry": 360,  # must exceed timeout
    "sync": False,
}

# --- LLM (see docs/architecture.html §7.4) ------------------------------------

LLM_PROVIDER = env("LLM_PROVIDER", default="mock")
LLM_BASE_URL = env("LLM_BASE_URL", default="")
LLM_API_KEY = env("LLM_API_KEY", default="")
LLM_MODEL = env("LLM_MODEL", default="mock")
LLM_VISION_BASE_URL = env("LLM_VISION_BASE_URL", default="") or LLM_BASE_URL
LLM_VISION_API_KEY = env("LLM_VISION_API_KEY", default="") or LLM_API_KEY
LLM_VISION_MODEL = env("LLM_VISION_MODEL", default="mock")
LLM_TIMEOUT_SECONDS = env.int("LLM_TIMEOUT_SECONDS", default=60)
# Simulated delay of the offline mock so the demo feels like a real call.
LLM_MOCK_LATENCY_SECONDS = env.float("LLM_MOCK_LATENCY_SECONDS", default=0.3)

# --- Business -----------------------------------------------------------------

COMPANY_SKU_PREFIX = env("COMPANY_SKU_PREFIX", default="FIT-")
DEFAULT_MARGIN = Decimal(env("DEFAULT_MARGIN", default="0.25"))
