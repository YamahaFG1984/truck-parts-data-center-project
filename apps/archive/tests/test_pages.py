"""Search, product, record and export pages (M28)."""

import pytest
from django.urls import reverse

from apps.archive.models import Membership, Product
from apps.archive.services import review
from apps.sources.models import SourceRecord

from .conftest import find_item

pytestmark = pytest.mark.django_db


@pytest.fixture
def browser(client, user, archive):
    client.force_login(user)
    return client


def page(client, name, *args, **params):
    response = client.get(reverse(name, args=args), params)
    assert response.status_code == 200
    return response.content.decode()


def record(key):
    return SourceRecord.objects.current().get(record_key=key)


def test_search_page_lists_products_with_what_matched(browser):
    html = page(browser, "archive:search", q="OE-TST-1001")
    assert "命中 2 个产品" in html and "OE / 互换号" in html and "X-001" in html
    home = page(browser, "archive:search")
    assert "条待人工确认" in home and "主数据.xlsx" in home


def test_product_page_shows_members_quotes_and_sources(browser, user):
    review.confirm_same(find_item("X-001~Y-001"), user, "对照目录确认")
    product = Membership.objects.get(record_key="X-001").product
    html = page(browser, "archive:product", product.pk)

    assert product.code in html and "已确认归一" in html
    assert "42.67" in html and "46.58" in html and "GBP" in html and "USD" in html
    assert "Price List!R2" in html and "Catalog Export!R2" in html
    assert "merge" in html and "对照目录确认" in html  # decision history
    assert "不换算" in html


def test_product_page_marks_member_disagreement(browser, user):
    review.confirm_same(find_item("X-008~Y-005"), user, "演示")
    product = Membership.objects.get(record_key="X-008").product
    assert "成员不一致：Left / Right" in page(browser, "archive:product", product.pk)


def test_a_merged_product_redirects_to_where_it_went(browser, user):
    review.confirm_same(find_item("X-001~Y-001"), user, "同一件")
    merged = Product.objects.get(status="merged")
    response = browser.get(reverse("archive:product", args=[merged.pk]))
    assert response.status_code == 302
    assert response.url == reverse("archive:product", args=[merged.merged_into_id])


def test_record_page_shows_the_original_row_and_field_sources(browser):
    html = page(browser, "archive:record", record("Y-002").pk)
    assert "Left Side Grille" in html and "Cross Ref" in html and "C3" in html
    assert "v1" in html and "Supplier Y.xlsx" in html


def test_record_page_explains_lookalikes_that_were_not_paired(browser):
    html = page(browser, "archive:record", record("X-003").pk)
    assert "X-004（Fan Shroud）尺寸相同但品类不同" in html
    sides = page(browser, "archive:record", record("Y-002").pk)
    assert "Y-005 同品类同适配，但位置是 Right，已按左右区分" in sides
    assert "X-008 同品类同适配，但两边的 OE 号没有一个相同" in sides


def test_record_page_labels_missing_fields(browser):
    assert "缺失：</b>OE 号、单价、币种" in page(browser, "archive:record", record("X-009").pk)


def test_exports_download_as_xlsx(browser):
    response = browser.get(reverse("archive:export", args=["quotes"]))
    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/vnd.openxmlformats")
    assert "filename*=UTF-8''" in response["Content-Disposition"]
    assert browser.get(reverse("archive:export", args=["nope"])).status_code == 404
