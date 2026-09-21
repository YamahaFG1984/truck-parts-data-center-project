"""Read supplier files cell by cell, keeping where every value came from
(docs/archive-design.html §5 step 2, §6).

Excel is read with openpyxl rather than pandas: lineage needs each cell's
coordinate, and the price check in M24 needs its number format.
"""

import csv
import datetime as dt
import io
from dataclasses import dataclass, field
from decimal import Decimal

import pdfplumber
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

HEADER_SCAN_ROWS = 20  # the header is looked for among the first rows that have content
MIN_CELLS_PER_ROW = 2  # rows with fewer filled cells are titles, notes or totals
CSV_ENCODINGS = ("utf-8-sig", "gb18030")


class ReadError(ValueError):
    """The file cannot be read; the message is shown to the user and stored on the file."""


class NoTableFound(ReadError):
    """A PDF opened fine but holds nothing that reads as a table."""


@dataclass(frozen=True)
class Cell:
    value: object  # int, float, datetime, str ... as stored in the file
    text: str  # the stored value as text; never the display format
    coord: str  # "G14"
    number_format: str = ""


@dataclass
class Row:
    row_no: int  # file row (Excel, CSV) or row within the page's table (PDF)
    cells: dict[str, Cell]  # header -> cell
    page: int | None = None  # PDF only, from 1 like a reader shows it
    table_no: int | None = None  # PDF only: nth table on that page

    def texts(self) -> dict[str, str]:
        return {header: cell.text for header, cell in self.cells.items()}


@dataclass
class Sheet:
    name: str
    header_row: int
    headers: list[str]
    rows: list[Row]
    skipped: list[tuple[int, str]] = field(default_factory=list)  # (row_no, why)
    notes: list[str] = field(default_factory=list)  # things a person should double-check


def read_source(source_file) -> list[Sheet]:
    readers = {"xlsx": read_workbook, "csv": read_csv, "pdf": read_pdf}
    reader = readers.get(source_file.file_format)
    if reader is None:
        raise ReadError(f"暂不支持读取 {source_file.get_file_format_display()} 文件。")
    with source_file.file.open("rb") as fh:
        sheets = reader(fh)
    if not sheets:
        raise ReadError("文件里没有找到带表头的数据表。")
    return sheets


def read_workbook(fh) -> list[Sheet]:
    try:
        workbook = load_workbook(fh, read_only=True, data_only=True)
    except Exception as exc:  # openpyxl raises many types for damaged files
        raise ReadError(f"无法读取 Excel 文件：{exc}") from exc
    sheets = []
    for worksheet in workbook.worksheets:
        grid = [
            [_cell(c, row_no, col_no) for col_no, c in enumerate(row, start=1)]
            for row_no, row in enumerate(worksheet.iter_rows(), start=1)
        ]
        sheet = _build_sheet(worksheet.title, grid)
        if sheet:
            sheets.append(sheet)
    workbook.close()
    return sheets


def read_csv(fh) -> list[Sheet]:
    data = fh.read()
    for encoding in CSV_ENCODINGS:
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ReadError("无法识别 CSV 的文字编码（支持 UTF-8 与 GB18030）。")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    grid = [
        [Cell(value, value.strip(), f"{get_column_letter(col_no)}{row_no}")
         for col_no, value in enumerate(row, start=1)]
        for row_no, row in enumerate(csv.reader(io.StringIO(text), dialect), start=1)
    ]
    sheet = _build_sheet("CSV", grid)
    return [sheet] if sheet else []


# Ruled tables first; tables laid out by text alignment only as a fallback, because
# the text strategy also finds "tables" in ordinary paragraphs.
PDF_STRATEGIES = [("lines", "表格线"), ("text", "文字对齐")]


def read_pdf(fh) -> list[Sheet]:
    try:
        pdf = pdfplumber.open(fh)
    except Exception as exc:  # pdfminer raises several types for damaged or locked files
        raise ReadError(f"无法打开 PDF：{exc}") from exc
    try:
        with pdf:
            if not any(page.chars for page in pdf.pages):
                raise NoTableFound("PDF 里没有可提取的文字，可能是扫描件。本阶段不做 OCR，"
                                   "请向供应商索取电子版或 Excel。")
            for strategy, _label in PDF_STRATEGIES:
                found = _pdf_tables(pdf, strategy)
                if found:
                    break
            else:
                raise NoTableFound("PDF 中没有识别到表格（表格线与文字对齐两种方式都试过）。"
                                   "请人工处理，或向供应商索取 Excel。")
    except ReadError:
        raise
    except Exception as exc:  # a page that opens but cannot be parsed
        raise ReadError(f"解析 PDF 时出错：{exc}") from exc
    return [sheet for sheet in _stitch(found) if sheet]


def _pdf_tables(pdf, strategy: str):
    """(page, table_no, rows, notes) with blank rows dropped, so row numbers match what
    a person counts on the page. Tables need two columns and a header-like first row."""
    found = []
    for page_no, page in enumerate(pdf.pages, start=1):
        settings = {"vertical_strategy": strategy, "horizontal_strategy": strategy}
        if strategy == "text" and page.chars:
            # Without outer edges the text strategy clips the last column at the right
            # edge of the aligned words, silently cutting off longer text.
            settings["explicit_vertical_lines"] = [min(c["x0"] for c in page.chars) - 1,
                                                   max(c["x1"] for c in page.chars) + 1]
        for table_no, table in enumerate(page.extract_tables(settings), start=1):
            rows = [[" ".join((c or "").split()) for c in row] for row in table]
            rows = [r for r in rows if any(r)]
            if not rows or len(rows[0]) < 2 or _filled_texts(rows[0]) < 2:
                continue
            notes = []
            if strategy == "text":
                rows, notes = _merge_split_headers(rows)
                notes.insert(0, f"第{page_no}页的表格没有表格线，按文字对齐识别，"
                                "列边界可能不准，请在列映射时核对样例。")
            found.append((page_no, table_no, rows, notes))
    return found


def _merge_split_headers(rows):
    """A column with a header but no data is a header phrase split by the text
    strategy ("Min" | "Order"): join it to the column on its left."""
    notes = []
    col = len(rows[0]) - 1
    while col > 0:
        empty = not any(r[col] for r in rows[1:] if col < len(r))
        if rows[0][col] and rows[0][col - 1] and empty:
            joined = f"{rows[0][col - 1]} {rows[0][col]}"
            notes.append(f"表头“{rows[0][col]}”下没有数据，已并入左侧，合为“{joined}”。")
            rows = [r[:col - 1] + [joined if i == 0 else r[col - 1]] + r[col + 1:]
                    for i, r in enumerate(rows)]
        col -= 1
    return rows, notes


def _stitch(found):
    """Join a table that continues at the top of the next page (same width) to the
    one before it; a header repeated on the new page is dropped."""
    tables = []  # [header, [(page, table_no, row_no, texts)], pages, notes]
    for page_no, table_no, rows, notes in found:
        current = tables[-1] if tables else None
        continues = (current and table_no == 1 and page_no == current[2][-1] + 1
                     and len(rows[0]) == len(current[0]))
        if not continues:
            current = [rows[0], [(page_no, table_no, 1, rows[0])], [page_no], []]
            tables.append(current)
            body = enumerate(rows[1:], start=2)
        else:
            current[2].append(page_no)
            body = ((i, r) for i, r in enumerate(rows, start=1) if r != current[0])
        current[1] += [(page_no, table_no, i, r) for i, r in body]
        current[3] += notes
    for index, (_header, rows, pages, notes) in enumerate(tables, start=1):
        span = f"第{pages[0]}页" if len(pages) == 1 else f"第{pages[0]}–{pages[-1]}页"
        grid = [[Cell(text, text, f"P{p}/T{t}/R{r}/C{c}") for c, text in enumerate(texts, 1)]
                for p, t, r, texts in rows]
        sheet = _build_sheet(f"表{index}（{span}）", grid,
                             positions=[(r, p, t) for p, t, r, _ in rows])
        if sheet:
            sheet.notes = notes
        yield sheet


def _filled_texts(texts: list[str]) -> int:
    return sum(1 for t in texts if t and not _numeric(t))


def _cell(cell, row_no: int, col_no: int) -> Cell:
    coord = f"{get_column_letter(col_no)}{row_no}"
    value = getattr(cell, "value", None)
    number_format = getattr(cell, "number_format", "") or ""
    return Cell(value, _as_text(value), coord, "" if number_format == "General" else number_format)


def _as_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, dt.datetime):
        return value.date().isoformat() if value.time() == dt.time() else value.isoformat(" ")
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, float):
        return format(Decimal(repr(value)).normalize(), "f")  # 80.2 not 80.20000000000000284
    return str(value).strip()


def _build_sheet(name: str, grid: list[list[Cell]], positions=None) -> Sheet | None:
    """grid[i] is file row i + 1, unless positions[i] gives (row_no, page, table_no).
    Picks the most header-like of the first filled rows."""
    filled = [i for i, row in enumerate(grid) if _filled(row) >= MIN_CELLS_PER_ROW]
    if not filled:
        return None
    header_index = max(filled[:HEADER_SCAN_ROWS], key=lambda i: (_text_cells(grid[i]), -i))
    headers = _unique_headers(grid[header_index])
    rows, skipped = [], []
    for index in range(header_index + 1, len(grid)):
        row = grid[index]
        row_no, page, table_no = positions[index] if positions else (index + 1, None, None)
        count = _filled(row)
        if count == 0:
            continue
        if count < MIN_CELLS_PER_ROW:
            text = next(c.text for c in row if c.text)
            skipped.append((row_no, f"只有一个单元格有内容（{text[:40]}），视为标题或备注"))
            continue
        cells = {h: row[i] for i, h in enumerate(headers) if i < len(row)}
        rows.append(Row(row_no, cells, page, table_no))
    # Columns with no header text are kept only if some row has data in them.
    used = {h for r in rows for h, c in r.cells.items() if c.text}
    header_cells = grid[header_index]
    keep = [h for h, cell in zip(headers, header_cells, strict=False) if cell.text or h in used]
    for r in rows:
        r.cells = {h: c for h, c in r.cells.items() if h in keep}
    header_row = (positions[header_index][0] if positions else header_index + 1)
    return Sheet(name, header_row, keep, rows, skipped)


def _filled(row: list[Cell]) -> int:
    return sum(1 for c in row if c.text)


def _text_cells(row: list[Cell]) -> int:
    """How header-like a row is: filled cells holding text, not numbers or dates."""
    return sum(1 for c in row if c.text and isinstance(c.value, str) and not _numeric(c.text))


def _numeric(text: str) -> bool:
    try:
        float(text.replace(",", ""))
    except ValueError:
        return False
    return True


def _unique_headers(cells: list[Cell]) -> list[str]:
    """Header texts; blanks become "列G", repeats get " (2)", " (3)"."""
    headers, seen = [], {}
    for index, cell in enumerate(cells, start=1):
        text = cell.text or ""
        if not text:
            headers.append(f"列{get_column_letter(index)}")
            continue
        seen[text] = seen.get(text, 0) + 1
        headers.append(text if seen[text] == 1 else f"{text} ({seen[text]})")
    return headers
