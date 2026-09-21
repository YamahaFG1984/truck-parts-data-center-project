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
