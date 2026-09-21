import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.sources.models import SourceFile
from apps.sources.services.readers import NoTableFound, ReadError, read_pdf, read_workbook

from .pdfgen import make_pdf
from .workbooks import workbook_bytes

HEADER = ["Source Ref", "Brand Number", "English Name", "Offer Price", "Curr.", "Min Order"]
ROWS = [
    ["Y-001", "Y01X", "Front Grille", "46.58", "USD", "5"],
    ["Y-002", "Y02L", "Left Side Grille", "54.24", "GBP", "20"],
    ["Y-003", "Y03X", "Fan Shroud", "61.9", "USD", "5"],
    ["Y-004", "Y04R", "Right Side Grille", "58.07", "GBP", "1"],
]


def read(pages, **kwargs):
    return read_pdf(io.BytesIO(make_pdf(pages, **kwargs)))


def test_a_ruled_table_keeps_page_table_and_row():
    [sheet] = read([[HEADER, *ROWS[:2]]])

    assert sheet.name == "表1（第1页）" and sheet.headers == HEADER
    first = sheet.rows[0]
    assert (first.page, first.table_no, first.row_no) == (1, 1, 2)  # row 1 is the header
    assert first.cells["English Name"].coord == "P1/T1/R2/C3"
    assert first.texts()["Offer Price"] == "46.58"


def test_a_table_continued_over_pages_is_one_table():
    pages = [[HEADER, *ROWS[:2]],
             [HEADER, ROWS[2]],  # header repeated at the top of page 2
             [ROWS[3]],  # page 3 continues without a header
             "Terms: FOB Ningbo, prices valid 30 days."]

    [sheet] = read(pages)

    assert sheet.name == "表1（第1–3页）"
    assert [(r.page, r.row_no, r.texts()["Source Ref"]) for r in sheet.rows] == [
        (1, 2, "Y-001"), (1, 3, "Y-002"), (2, 2, "Y-003"), (3, 1, "Y-004")]


def test_tables_of_different_width_stay_separate():
    sheets = read([[HEADER, ROWS[0]], [["Part", "Note"], ["P-9", "discontinued"]]])

    assert [s.name for s in sheets] == ["表1（第1页）", "表2（第2页）"]
    assert sheets[1].headers == ["Part", "Note"]


def test_a_table_without_lines_is_read_by_text_alignment():
    [sheet] = read([[HEADER, *ROWS[:2]]], ruled=False)

    assert sheet.headers == HEADER
    assert [r.row_no for r in sheet.rows] == [2, 3]  # blank spacing rows are not counted


def test_a_pdf_without_any_table_says_so():
    with pytest.raises(NoTableFound, match="没有识别到表格"):
        read(["Dear customer,\nplease find our new prices attached."])


def test_a_pdf_without_text_is_treated_as_a_scan():
    with pytest.raises(NoTableFound, match="扫描件"):
        read([[["", ""], ["", ""]]])  # only lines, no characters


@pytest.mark.parametrize("data", [b"%PDF-1.4\n garbage", make_pdf([[HEADER, ROWS[0]]])[:200]])
def test_a_damaged_pdf_raises_a_readable_error(data):
    with pytest.raises(ReadError, match="PDF"):
        read_pdf(io.BytesIO(data))


def test_pdf_and_excel_with_the_same_content_read_the_same():
    [from_pdf] = read([[HEADER, *ROWS]])
    [from_xlsx] = read_workbook(io.BytesIO(workbook_bytes(HEADER, ROWS)))

    assert from_pdf.headers == from_xlsx.headers
    assert [r.texts() for r in from_pdf.rows] == [r.texts() for r in from_xlsx.rows]


@pytest.mark.django_db
class TestPdfUpload:
    @pytest.fixture
    def ops(self, client, django_user_model):
        client.force_login(django_user_model.objects.create_user("ops", password="x"))
        return client

    def upload(self, client, data):
        return client.post(reverse("sources:list"),
                           {"file": SimpleUploadedFile("catalog.pdf", data),
                            "new_supplier": "Demo Supplier P"}, follow=True)

    def test_a_pdf_goes_through_the_same_mapping_step(self, ops):
        response = self.upload(ops, make_pdf([[HEADER, *ROWS]]))

        body = response.content.decode()
        assert "列映射" in body and "表1（第1页）" in body and "Y01X" in body
        assert "文字对齐" not in body  # a ruled table raises no alignment warning

    def test_alignment_notes_are_shown_where_the_mapping_is_checked(self, ops):
        response = self.upload(ops, make_pdf([[HEADER, *ROWS]], ruled=False))

        assert "按文字对齐识别" in response.content.decode()
        assert SourceFile.objects.get().stats["sheets"][0]["rows"] == 4

    def test_a_pdf_without_tables_fails_but_is_kept(self, ops):
        data = make_pdf(["No table here, only a cover letter."])

        response = self.upload(ops, data)

        source = SourceFile.objects.get()
        assert source.status == "failed" and "没有识别到表格" in response.content.decode()
        download = ops.get(reverse("sources:original", args=[source.pk]))
        assert b"".join(download.streaming_content) == data
