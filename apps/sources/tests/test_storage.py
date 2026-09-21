import hashlib
import os

import pytest

from apps.sources.models import SourceFile
from apps.sources.services import storage
from apps.sources.services.storage import DuplicateFile, UploadRejected, store_upload
from apps.suppliers.tests.factories import SupplierFactory

from .conftest import upload, xlsx_bytes

pytestmark = pytest.mark.django_db


def test_original_is_archived_under_a_uuid_name_with_its_hash(supplier, django_user_model):
    user = django_user_model.objects.create_user("ops", password="x")
    data = xlsx_bytes()

    source = store_upload(upload(data), supplier, user)

    assert source.original_name == "供应商报价 2026.xlsx"
    assert source.sha256 == hashlib.sha256(data).hexdigest()
    assert (source.size_bytes, source.file_format, source.status) == (len(data), "xlsx", "uploaded")
    assert source.uploaded_by == user
    assert source.file.name.startswith("sources/") and source.file.name.endswith(".xlsx")
    assert "供应商" not in source.file.name  # the client's file name never reaches the disk
    with source.file.open("rb") as fh:
        assert fh.read() == data


def test_archived_original_is_read_only_on_disk(source_file):
    assert os.stat(source_file.file.path).st_mode & 0o222 == 0


def test_same_file_from_the_same_supplier_is_refused(supplier, source_file):
    with pytest.raises(DuplicateFile) as exc:
        store_upload(upload(xlsx_bytes(), name="renamed copy.xlsx"), supplier)

    assert exc.value.existing == source_file
    assert f"#{source_file.pk}" in str(exc.value)
    assert SourceFile.objects.count() == 1


def test_same_file_from_another_supplier_is_archived_separately(source_file):
    other = store_upload(upload(xlsx_bytes()), SupplierFactory(name="Demo Supplier B"))

    assert other.pk != source_file.pk and other.sha256 == source_file.sha256


def test_changed_content_is_a_new_file_even_with_the_same_name(supplier, source_file):
    newer = store_upload(upload(xlsx_bytes("Bug Screen")), supplier)

    assert newer.original_name == source_file.original_name and newer.pk != source_file.pk


@pytest.mark.parametrize("name", ["old.xls", "notes.docx", "no_extension"])
def test_unsupported_formats_are_refused(supplier, name):
    with pytest.raises(UploadRejected, match="只支持"):
        store_upload(upload(b"whatever", name=name), supplier)


@pytest.mark.parametrize(("name", "data"), [
    ("quote.xlsx", b"Part No.,Price\nA-1,10\n"),
    ("catalog.pdf", b"PK\x03\x04 not really a pdf"),
])
def test_content_must_match_the_extension(supplier, name, data):
    with pytest.raises(UploadRejected, match="内容不是"):
        store_upload(upload(data, name=name), supplier)
    assert not SourceFile.objects.exists()


def test_csv_and_pdf_are_accepted(supplier):
    csv = store_upload(upload(b"Part No.,Price\nA-1,10\n", name="quote.csv"), supplier)
    pdf = store_upload(upload(b"%PDF-1.4\n%fake body", name="catalog.pdf"), supplier)

    assert (csv.file_format, pdf.file_format) == ("csv", "pdf")


def test_oversized_upload_is_refused(supplier, monkeypatch):
    monkeypatch.setattr(storage, "MAX_UPLOAD_MB", 0)

    with pytest.raises(UploadRejected, match="超过"):
        store_upload(upload(xlsx_bytes()), supplier)


def test_path_components_in_the_uploaded_name_are_dropped(supplier):
    source = store_upload(upload(b"a,b\n1,2\n", name="../../etc/quote.csv"), supplier)

    assert source.original_name == "quote.csv" and source.file.name.startswith("sources/")
