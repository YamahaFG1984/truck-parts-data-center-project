import pytest
from django.contrib.auth import get_user_model
from django.db import connection

from apps.users.models import User


def test_auth_user_model_is_project_user():
    assert get_user_model() is User


@pytest.mark.django_db
def test_create_user():
    user = User.objects.create_user(username="sales", password="s3cret-pass")

    assert user.pk is not None
    assert user.check_password("s3cret-pass")
    assert not user.is_staff
    assert not user.is_superuser


@pytest.mark.django_db
def test_create_superuser():
    admin = User.objects.create_superuser(username="boss", email="b@example.com", password="x-pass")

    assert admin.is_staff
    assert admin.is_superuser


@pytest.mark.django_db
def test_pg_trgm_enabled_on_postgres():
    if connection.vendor != "postgresql":
        pytest.skip("pg_trgm only exists on PostgreSQL")
    with connection.cursor() as cursor:
        cursor.execute("select 1 from pg_extension where extname = 'pg_trgm'")
        assert cursor.fetchone() == (1,)
