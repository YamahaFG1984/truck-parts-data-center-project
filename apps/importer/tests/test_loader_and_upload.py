import io
from pathlib import Path

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from openpyxl import Workbook

from apps.importer import forms as importer_forms
from apps.importer.models import ImportBatch
from apps.importer.services.loader import LoaderError, read_table
from scripts.make_supplier_excel import write_supplier_excel

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@pytest.fixture(autouse=True)
def _media_in_tmp(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"


@pytest.fixture
def messy_xlsx(tmp_path) -> Path:
    samples = [{"oe": f"2044390{i}", "name_en": "Brake Pad Set", "vehicle": "Volvo FH12"}
               for i in range(10)]
    return write_supplier_excel(tmp_path / "messy.xlsx", samples, taken=set(), seed=1)


def _xlsx_bytes(rows) -> bytes:
    wb = Workbook()
    for row in rows:
        wb.active.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# --- read_table --------------------------------------------------------------------------


def test_messy_supplier_excel_header_found_below_letterhead(messy_xlsx):
    table = read_table(messy_xlsx, messy_xlsx.name)

    assert table.header_row == 3
    assert table.headers == [
        "Part No.", "OEM NO", "Ref", "Description", "适用车型", "MOQ", "FOB Price(USD)", "Packing",
    ]
    assert table.row_count == 80
    assert table.row_numbers[0] == 4
    assert all(isinstance(v, str) for row in table.rows for v in row.values())


def test_numbers_stay_text_leading_zero_and_no_scientific_notation():
    data = _xlsx_bytes([
        ["Part No", "Bosch No", "Qty"],
        ["P1", "0986424813", 50],  # typed as text in Excel
        ["P2", 986424813, 1e8],  # typed as numbers
        ["P3", "A 000 420 15 20", 12.5],
    ])

    rows = read_table(io.BytesIO(data), "t.xlsx").rows

    assert [r["Bosch No"] for r in rows] == ["0986424813", "986424813", "A 000 420 15 20"]
    assert [r["Qty"] for r in rows] == ["50", "100000000", "12.5"]


def test_header_with_fewer_cells_than_a_data_row_is_still_found():
    data = _xlsx_bytes([
        ["Part No", "OE", None, None],
        ["A1", "20443906", "12.5", "orphan note"],
    ])

    table = read_table(io.BytesIO(data), "t.xlsx")

    assert table.header_row == 1
    assert table.headers == ["Part No", "OE", "列3", "列4"]  # data columns are never dropped


def test_blank_rows_are_dropped_but_row_numbers_are_kept():
    data = _xlsx_bytes([["Part No", "OE"], ["A1", "1"], [None, None], ["A2", "2"]])

    table = read_table(io.BytesIO(data), "t.xlsx")

    assert table.row_numbers == [2, 4]


def test_duplicate_headers_get_suffixes():
    data = _xlsx_bytes([["OE", "OE", "Price"], ["1", "2", "3"]])

    assert read_table(io.BytesIO(data), "t.xlsx").headers == ["OE", "OE (2)", "Price"]


def test_gbk_csv_is_decoded():
    text = "品名,OE号,单价\n刹车片,20443906,18.5\n空气滤清器,0986424813,6\n"

    table = read_table(io.BytesIO(text.encode("gbk")), "报价.csv")

    assert table.headers == ["品名", "OE号", "单价"]
    assert table.rows[1] == {"品名": "空气滤清器", "OE号": "0986424813", "单价": "6"}


def test_semicolon_csv_with_bom():
    text = "﻿Part No;OE\nA1;20443906\n"

    table = read_table(io.BytesIO(text.encode("utf-8")), "x.csv")

    assert table.rows == [{"Part No": "A1", "OE": "20443906"}]


@pytest.mark.parametrize(
    ("name", "content", "message"),
    [
        ("old.xls", b"\xd0\xcf\x11\xe0", "另存为 .xlsx"),
        ("notes.txt", b"hello", "不支持的文件类型"),
        ("broken.xlsx", b"not a zip file", "无法读取"),
        ("empty.csv", b"\n\n", "没有任何数据"),
    ],
)
def test_unreadable_files_raise_friendly_errors(name, content, message):
    with pytest.raises(LoaderError, match=message):
        read_table(io.BytesIO(content), name)


# --- upload and preview views -----------------------------------------------------------


@pytest.fixture
def ops_client(client, django_user_model):
    client.force_login(django_user_model.objects.create_user("ops", password="x"))
    return client


@pytest.mark.django_db
def test_upload_saves_under_uuid_name_and_redirects_to_preview(ops_client, messy_xlsx):
    upload = SimpleUploadedFile("供应商报价 2026.xlsx", messy_xlsx.read_bytes(), content_type=XLSX)

    response = ops_client.post(reverse("importer:upload"), {"file": upload})

    batch = ImportBatch.objects.get()
    assert response.status_code == 302
    assert response.url == reverse("importer:preview", args=[batch.pk])
    assert batch.original_name == "供应商报价 2026.xlsx"
    assert batch.file.name.startswith("imports/") and batch.file.name.endswith(".xlsx")
    assert "供应商" not in batch.file.name
    assert (batch.header_row, batch.stats) == (3, {"rows": 80, "columns": 8})
    assert batch.status == "uploaded"


@pytest.mark.django_db
def test_preview_shows_header_and_first_rows(ops_client, messy_xlsx):
    upload = SimpleUploadedFile("q.xlsx", messy_xlsx.read_bytes(), content_type=XLSX)
    ops_client.post(reverse("importer:upload"), {"file": upload})
    batch = ImportBatch.objects.get()

    response = ops_client.get(reverse("importer:preview", args=[batch.pk]))

    body = response.content.decode()
    assert response.status_code == 200
    assert "第 3 行" in body and "OEM NO" in body and "FOB Price(USD)" in body
    assert len(response.context["preview"]) == 20


@pytest.mark.django_db
def test_upload_rejects_xls_with_save_as_hint(ops_client):
    upload = SimpleUploadedFile(
        "old.xls", b"\xd0\xcf\x11\xe0", content_type="application/vnd.ms-excel"
    )

    response = ops_client.post(reverse("importer:upload"), {"file": upload})

    assert response.status_code == 200
    assert "另存为 .xlsx" in response.content.decode()
    assert not ImportBatch.objects.exists()


@pytest.mark.django_db
def test_upload_rejects_oversized_file(ops_client, monkeypatch):
    monkeypatch.setattr(importer_forms, "MAX_UPLOAD_MB", 0)
    upload = SimpleUploadedFile("big.xlsx", _xlsx_bytes([["a"], ["b"]]), content_type=XLSX)

    response = ops_client.post(reverse("importer:upload"), {"file": upload})

    assert "文件超过" in response.content.decode()
    assert not ImportBatch.objects.exists()


@pytest.mark.django_db
def test_upload_rejects_unreadable_xlsx_without_creating_a_batch(ops_client):
    upload = SimpleUploadedFile("broken.xlsx", b"not a zip file", content_type=XLSX)

    response = ops_client.post(reverse("importer:upload"), {"file": upload})

    assert "无法读取" in response.content.decode()
    assert not ImportBatch.objects.exists()


@pytest.mark.django_db
def test_upload_page_lists_recent_batches(ops_client, messy_xlsx):
    for _ in range(2):
        upload = SimpleUploadedFile("q.xlsx", messy_xlsx.read_bytes(), content_type=XLSX)
        ops_client.post(reverse("importer:upload"), {"file": upload})

    response = ops_client.get(reverse("importer:upload"))

    assert len(response.context["recent"]) == 2


@pytest.mark.django_db
@pytest.mark.parametrize("model", ["importbatch", "importrow"])
def test_admin_pages(admin_client, model):
    assert admin_client.get(reverse(f"admin:importer_{model}_changelist")).status_code == 200
