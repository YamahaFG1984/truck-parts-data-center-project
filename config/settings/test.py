"""pytest / CI: fast, offline, deterministic."""

from .base import *  # noqa: F403
from .base import Q_CLUSTER

DEBUG = False
LLM_PROVIDER = "mock"
LLM_MOCK_LATENCY_SECONDS = 0
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# Serve static files straight from app/static dirs; no collectstatic needed.
WHITENOISE_USE_FINDERS = True
WHITENOISE_AUTOREFRESH = True

# Run django-q2 tasks inline so tests never need a qcluster process.
Q_CLUSTER = {**Q_CLUSTER, "sync": True}
