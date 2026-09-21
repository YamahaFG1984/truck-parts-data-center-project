import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.sources.models import MappingTemplate, SourceFile
from apps.suppliers.models import Supplier

from .workbooks import HEADERS_B, workbook_bytes

pytestmark = pytest.mark.django_db
LIST = reverse("sources:list")


@pytest.fixture
def ops(client, django_user_model):
    client.force_login(django_user_model.objects.create_user("ops", password="x"))
    return client


def post_file(client, data, name="quote.xlsx", follow=False, **fields):
    return client.post(LIST, {"file": SimpleUploadedFile(name, data), **fields}, follow=follow)


def test_upload_with_a_new_supplier_goes_to_mapping(ops):
    response = post_file(ops, workbook_bytes(), new_supplier="Demo Supplier C")

    source = SourceFile.objects.get()
    assert source.supplier.name == "Demo Supplier C"
    assert response.url == reverse("sources:mapping", args=[source.pk])
    assert source.stats["sheets"][0]["rows"] == 3


def test_supplier_is_required(ops):
    response = post_file(ops, workbook_bytes())

    assert "每份资料都要归属一个供应商" in response.content.decode()
    assert not SourceFile.objects.exists()


def test_the_same_file_again_points_at_the_archived_one(ops, supplier):
    data = workbook_bytes()  # one set of bytes: each save embeds a new timestamp
    post_file(ops, data, supplier=supplier.pk)
    first = SourceFile.objects.get()

    response = post_file(ops, data, name="copy.xlsx", supplier=supplier.pk, follow=True)

    assert response.redirect_chain[-1][0] == reverse("sources:detail", args=[first.pk])
    assert f"#{first.pk}" in response.content.decode()


def test_mapping_page_shows_suggestions_and_samples(ops, supplier):
    post_file(ops, workbook_bytes(HEADERS_B), supplier=supplier.pk)
    source = SourceFile.objects.get()

    body = ops.get(reverse("sources:mapping", args=[source.pk])).content.decode()

    assert "Brand Number" in body and "X-01-00" in body and "同义词" in body
    assert SourceFile.objects.get().status == "uploaded"  # suggestions are not a confirmation


def test_confirming_saves_the_mapping_and_a_template(ops, supplier):
    post_file(ops, workbook_bytes(), supplier=supplier.pk)
    source = SourceFile.objects.get()
    url = reverse("sources:mapping", args=[source.pk])
    ops.get(url)

    response = ops.post(url, {"field__0__4": "note"}, follow=True)

    source.refresh_from_db()
    assert source.status == "mapped" and source.mapping["confirmed"]
    position = source.mapping["sheets"][0]["columns"][4]
    assert (position["field"], position["source"]) == ("note", "manual")
    assert MappingTemplate.objects.filter(supplier=supplier).exists()
    assert "列映射已确认" in response.content.decode()


def test_an_invalid_mapping_is_not_confirmed(ops, supplier):
    post_file(ops, workbook_bytes(), supplier=supplier.pk)
    source = SourceFile.objects.get()

    response = ops.post(reverse("sources:mapping", args=[source.pk]),
                        {"field__0__7": "moq"})  # price column chosen as a second MOQ

    assert "只能对应一列" in response.content.decode()
    assert SourceFile.objects.get().status == "uploaded"


def test_an_unreadable_file_is_kept_and_explained(ops, supplier):
    response = post_file(ops, b"PK\x03\x04 truncated", supplier=supplier.pk, follow=True)

    source = SourceFile.objects.get()
    assert source.status == "failed" and "无法读取 Excel" in source.error
    assert "无法读取 Excel" in response.content.decode()
    download = ops.get(reverse("sources:original", args=[source.pk]))
    assert b"".join(download.streaming_content) == b"PK\x03\x04 truncated"


def test_original_download_uses_the_original_name(ops, supplier):
    post_file(ops, workbook_bytes(), name="报价 9月.xlsx", supplier=supplier.pk)
    source = SourceFile.objects.get()

    response = ops.get(reverse("sources:original", args=[source.pk]))

    assert "attachment" in response["Content-Disposition"]
    assert "9%E6%9C%88.xlsx" in response["Content-Disposition"]  # RFC 5987 encoded name


def test_pages_need_login(client):
    assert client.get(LIST).status_code == 302
    assert Supplier.objects.count() == 0
