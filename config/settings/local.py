"""Developer machine: DEBUG on, debug toolbar."""

from .base import *  # noqa: F403
from .base import INSTALLED_APPS, MIDDLEWARE

DEBUG = True

INSTALLED_APPS = [*INSTALLED_APPS, "debug_toolbar"]
MIDDLEWARE = ["debug_toolbar.middleware.DebugToolbarMiddleware", *MIDDLEWARE]
INTERNAL_IPS = ["127.0.0.1"]
# Start collapsed: expanded, it covers the page (and the login button on phones).
DEBUG_TOOLBAR_CONFIG = {"SHOW_COLLAPSED": True}

# Serve static files straight from app/static dirs; no collectstatic needed.
WHITENOISE_USE_FINDERS = True
WHITENOISE_AUTOREFRESH = True
