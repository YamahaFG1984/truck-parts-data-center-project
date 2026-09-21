import pytest
from django.urls import reverse

from apps.archive.models import Product, ReviewItem

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("model", ["product", "reviewitem", "decisionlog", "fieldchoice"])
def test_admin_pages_open_and_are_read_only(admin_client, archive, model):
    assert admin_client.get(reverse(f"admin:archive_{model}_changelist")).status_code == 200
    assert admin_client.get(reverse(f"admin:archive_{model}_add")).status_code == 403


def test_a_product_page_lists_its_member(admin_client, archive):
    product = Product.objects.first()

    body = admin_client.get(reverse("admin:archive_product_change", args=[product.pk])).content

    assert product.memberships.get().record_key.encode() in body
    assert ReviewItem.objects.exists()
