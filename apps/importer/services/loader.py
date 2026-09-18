"""Read supplier spreadsheets into a clean table (docs/architecture.html §7.5).

Every cell is read as text: part numbers must never become numbers, lose leading
zeros or turn into scientific notation. Formulas are not evaluated (openpyxl
reads cached values). Dry-run and execute arrive with the column mapping (M14).
"""

import csv
import io
import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

HEADER_SCAN_ROWS = 10  # the header is the fullest row among the first 10
SUPPORTED_EXTENSIONS = {".xlsx", ".csv"}
CSV_ENCODINGS = ["utf-8-sig", "gb18030"]  # gb18030 is a superset of gbk / gb2312
XLS_MESSAGE = "暂不支持旧版 .xls 文件，请在 Excel 中另存为 .xlsx 后再上传。"


class LoaderError(Exception):
    """The file cannot be read as a table; the message is shown to the user."""


@dataclass
class Table:
    headers: list[str]
    rows: list[dict[str, str]]  # header -> cell text, empty cells as ""
    row_numbers: list[int]  # spreadsheet row number (1-based) of each row
    header_row: int  # spreadsheet row number of the header
    extra: dict = field(default_factory=dict)

    @property
    def row_count(self) -> int:
        return len(self.rows)


def read_table(source, filename: str) -> Table:
    """Parse an .xlsx or .csv file object (or path) into a Table."""
    suffix = Path(filename).suffix.lower()
    if suffix == ".xls":
        raise LoaderError(XLS_MESSAGE)
    if suffix not in SUPPORTED_EXTENSIONS:
        raise LoaderError(f"不支持的文件类型 {suffix or '（无扩展名）'}，请上传 .xlsx 或 .csv。")

    frame = _read_csv(source) if suffix == ".csv" else _read_xlsx(source)
    frame = frame.fillna("").astype(str).apply(lambda col: col.str.strip())
    frame = frame.loc[(frame != "").any(axis=1)]  # drop blank rows, keep original index
    if frame.empty:
        raise LoaderError("文件里没有任何数据。")

    header_pos = _find_header(frame)
    header_values = frame.iloc[header_pos].tolist()
    headers = _unique_headers(header_values)
    body = frame.iloc[header_pos + 1:]
    # Keep a column if it has a header or any data: never drop values silently.
    keep = [i for i, h in enumerate(header_values) if h or (body.iloc[:, i] != "").any()]

    rows = [{headers[i]: record[i] for i in keep} for record in body.itertuples(index=False)]
    return Table(
        headers=[headers[i] for i in keep],
        rows=rows,
        row_numbers=[int(idx) + 1 for idx in body.index],
        header_row=int(frame.index[header_pos]) + 1,
    )


def _read_xlsx(source) -> pd.DataFrame:
    try:
        return pd.read_excel(
            source, header=None, dtype=str, engine="openpyxl", keep_default_na=False
        )
    except Exception as exc:  # openpyxl raises many types for broken files
        raise LoaderError("无法读取这个 Excel 文件，请确认它是有效的 .xlsx。") from exc


def _read_csv(source) -> pd.DataFrame:
    data = source.read() if hasattr(source, "read") else Path(source).read_bytes()
    for encoding in CSV_ENCODINGS:
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise LoaderError("无法识别 CSV 的文字编码，请另存为 UTF-8 或 .xlsx。")
    try:
        delimiter = csv.Sniffer().sniff(text[:4096], delimiters=",;\t").delimiter
    except csv.Error:
        delimiter = ","
    return pd.read_csv(
        io.StringIO(text), header=None, dtype=str, sep=delimiter,
        keep_default_na=False, skip_blank_lines=False, engine="python",
    )


_NUMBER = re.compile(r"^[+-]?[\d\s,]*\.?\d+$")


def _find_header(frame: pd.DataFrame) -> int:
    """Position (not label) of the header among the first HEADER_SCAN_ROWS rows.

    Headers are words; data rows usually contain numbers (part numbers, prices,
    quantities). So rank rows by how many text cells they have, then by how few
    numeric cells; the earliest best row wins. Company letterheads above the header
    lose because they fill only one or two cells.
    """
    def score(i):
        cells = [c for c in frame.iloc[i].tolist() if c]
        numeric = sum(1 for c in cells if _NUMBER.match(c))
        return (len(cells) - numeric, -numeric)

    scores = [score(i) for i in range(min(HEADER_SCAN_ROWS, len(frame)))]
    return scores.index(max(scores))


def _unique_headers(values: list[str]) -> list[str]:
    headers, seen = [], {}
    for i, value in enumerate(values, start=1):
        name = value or f"列{i}"
        seen[name] = seen.get(name, 0) + 1
        headers.append(name if seen[name] == 1 else f"{name} ({seen[name]})")
    return headers
