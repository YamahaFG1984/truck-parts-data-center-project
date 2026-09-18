import pytest
from django.urls import reverse


@pytest.mark.django_db
def test_home_redirects_anonymous_user_to_login(client):
    response = client.get(reverse("core:home"))

    assert response.status_code == 302
    assert response.url.startswith(reverse("login"))


@pytest.mark.django_db
def test_home_renders_for_logged_in_user(client, django_user_model):
    user = django_user_model.objects.create_user(username="demo", password="demo-pass")
    client.force_login(user)

    response = client.get(reverse("core:home"))

    assert response.status_code == 200
    assert "卡车配件 AI 产品数据中心" in response.content.decode()
