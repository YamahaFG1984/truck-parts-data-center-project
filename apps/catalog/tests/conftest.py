import pytest


@pytest.fixture(autouse=True)
def _media_in_tmp(settings, tmp_path):
    """Uploaded test images go to a throwaway directory, never to media/."""
    settings.MEDIA_ROOT = tmp_path / "media"
