"""Repository-wide pytest hooks."""

import pytest
from django.db import connection


def pytest_collection_modifyitems(config, items):
    """Skip @pytest.mark.postgres tests when running on the SQLite fallback."""
    if connection.vendor == "postgresql":
        return
    skip = pytest.mark.skip(reason="needs PostgreSQL (pg_trgm)")
    for item in items:
        if "postgres" in item.keywords:
            item.add_marker(skip)
