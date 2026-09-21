import io

import pytest

from apps.sources.services.readers import ReadError, read_csv, read_workbook

from .workbooks import HEADERS_A, workbook_bytes


def read(data: bytes):
    return read_workbook(io.BytesIO(data))


def test_cells_keep_their_sheet_row_and_coordinate():
    [sheet] = read(workbook_bytes(sheet="报价明细"))

    assert (sheet.name, sheet.header_row, sheet.headers) == ("报价明细", 1, HEADERS_A)
    second = sheet.rows[1]
    assert second.row_no == 3
    assert second.cells["Supplier SKU"].coord == "B3"
    assert second.cells["Product Description"].text == "Side Grille, Left side"


def test_numbers_keep_their_value_and_format_not_the_displayed_text():
    [sheet] = read(workbook_bytes())
    price = sheet.rows[1].cells["Unit Price"]

    assert (price.value, price.text, price.number_format) == (51.01, "51.01", "$#,##0.00")
    assert sheet.rows[2].cells["Unit Price"].text == "80.2"  # no float noise
    assert sheet.rows[0].cells["MOQ"].text == "2"


def test_dates_are_read_as_iso_dates():
    [sheet] = read(workbook_bytes())

    assert sheet.rows[0].cells["Quote Date"].text == "2026-08-03"


def test_header_is_found_below_banner_rows_and_footers_are_reported():
    [sheet] = read(workbook_bytes(title_rows=["Demo Parts Co. — price list", "Valid 30 days"],
                                  footer="Prices exclude freight"))

    assert sheet.header_row == 3 and len(sheet.rows) == 3
    assert sheet.rows[0].row_no == 4
    assert [row for row, _ in sheet.skipped] == [8]
    assert "Prices exclude freight" in sheet.skipped[0][1]


def test_empty_sheets_are_left_out():
    sheets = read(workbook_bytes(extra_sheets=["Notes"]))

    assert [s.name for s in sheets] == ["Quote"]


def test_blank_and_repeated_headers_get_distinct_names():
    headers = ["Part No.", "", "Price", "Price"]
    [sheet] = read(workbook_bytes(headers, [["P-1", "extra", 1.5, 2.5]]))

    assert sheet.headers == ["Part No.", "列B", "Price", "Price (2)"]
    assert sheet.rows[0].cells["Price (2)"].text == "2.5"


def test_damaged_workbook_raises_a_readable_error():
    with pytest.raises(ReadError, match="无法读取 Excel"):
        read(b"PK\x03\x04 truncated zip")


@pytest.mark.parametrize("encoding", ["utf-8-sig", "gb18030"])
def test_csv_in_common_encodings_and_delimiters(encoding):
    text = "零件号;名称;单价\nP-1;前格栅;12.5\nP-2;风扇罩;8\n"

    [sheet] = read_csv(io.BytesIO(text.encode(encoding)))

    assert sheet.headers == ["零件号", "名称", "单价"]
    assert sheet.rows[1].cells["名称"].text == "风扇罩"
    assert sheet.rows[1].cells["单价"].coord == "C3"


def test_csv_in_an_unknown_encoding_is_refused():
    with pytest.raises(ReadError, match="编码"):
        read_csv(io.BytesIO("a,b\n1,2\n".encode("utf-16")))
