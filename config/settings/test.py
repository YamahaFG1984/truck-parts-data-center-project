"""pytest / CI: fast, offline, deterministic."""

from .base import *  # noqa: F403

DEBUG = False
LLM_PROVIDER = "mock"
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# Serve static files straight from app/static dirs; no collectstatic needed.
WHITENOISE_USE_FINDERS = True
WHITENOISE_AUTOREFRESH = True
