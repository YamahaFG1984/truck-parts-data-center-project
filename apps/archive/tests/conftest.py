import pytest

from apps.sources.tests.dataset import ingest_both


@pytest.fixture(autouse=True)
def _media_in_tmp(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user("ops", password="x")


@pytest.fixture
def archive(user):
    """Both synthetic suppliers ingested; enrolment and matching ran on commit."""
    return ingest_both(user)


def find_item(key: str, status: str | None = "open"):
    """The item for "X-001~Y-001" (a pair) or "X-009" (a single record)."""
    from apps.archive.models import ReviewItem

    items = ReviewItem.objects.all() if status is None else ReviewItem.objects.filter(
        status=status)
    for item in items.order_by("-id"):
        keys = [item.identity_a.split(":", 1)[1]]
        if item.identity_b:
            keys.append(item.identity_b.split(":", 1)[1])
        if sorted(keys) == sorted(key.split("~")):  # identities sort as text: 10: < 9:
            return item
    raise LookupError(key)
