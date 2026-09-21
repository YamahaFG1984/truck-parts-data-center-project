import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from openpyxl import Workbook

from apps.sources.models import SourceRecord
from apps.sources.services.storage import store_upload
from apps.suppliers.tests.factories import SupplierFactory


@pytest.fixture(autouse=True)
def _media_in_tmp(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"


def xlsx_bytes(value="Front Grille") -> bytes:
    workbook = Workbook()
    workbook.active["A1"] = value
    out = io.BytesIO()
    workbook.save(out)
    return out.getvalue()


def upload(data: bytes, name="供应商报价 2026.xlsx") -> SimpleUploadedFile:
    return SimpleUploadedFile(name, data)


@pytest.fixture
def supplier(db):
    return SupplierFactory(name="Demo Supplier A")


@pytest.fixture
def source_file(supplier):
    return store_upload(upload(xlsx_bytes()), supplier)


def make_record(source_file, row_no=2, **overrides) -> SourceRecord:
    fields = {
        "source_file": source_file, "supplier": source_file.supplier,
        "record_key": f"R-{row_no:03d}", "key_kind": SourceRecord.KeyKind.SOURCE_ID,
        "locator": f"Sheet1!R{row_no}", "sheet": "Sheet1", "row_no": row_no,
        "raw": {"Part No.": "X-1"}, "content_hash": "0" * 64,
    }
    return SourceRecord.objects.create(**(fields | overrides))
