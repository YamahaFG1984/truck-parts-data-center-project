"""A minimal PDF writer for tests: ruled tables and plain text, Helvetica, ASCII.

Real supplier catalogs are not available to the test suite, and adding a PDF
library only for tests is not worth a dependency; this is enough to exercise
pdfplumber's table finding with page, table and row positions.
"""

PAGE_W, PAGE_H = 595, 842  # A4 in points


def make_pdf(pages: list, *, col_width: int = 80, row_height: int = 18,
             ruled: bool = True) -> bytes:
    """pages: each item is a list of rows (one table) or a str (text only).
    ruled=False lays the table out by text alignment alone, without lines."""
    streams = []
    for page in pages:
        if isinstance(page, str):
            lines = page.splitlines() or [""]
            ops = [f"BT /F1 11 Tf 50 {780 - 16 * i} Td ({_esc(line)}) Tj ET"
                   for i, line in enumerate(lines)]
        else:
            ops = _table_ops(page, col_width, row_height, ruled)
        streams.append("\n".join(ops).encode("latin-1"))

    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", None,
               b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    kids = []
    for stream in streams:
        page_id, content_id = len(objects) + 1, len(objects) + 2
        kids.append(page_id)
        objects.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_W} {PAGE_H}] "
                       f"/Resources << /Font << /F1 3 0 R >> >> "
                       f"/Contents {content_id} 0 R >>".encode())
        objects.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
    objects[1] = (f"<< /Type /Pages /Kids [{' '.join(f'{k} 0 R' for k in kids)}] "
                  f"/Count {len(kids)} >>").encode()

    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1, xref)
    return bytes(out)


def _table_ops(rows, col_width, row_height, ruled):
    left, top = 30, 800
    cols = max(len(r) for r in rows)
    right, bottom = left + cols * col_width, top - len(rows) * row_height
    ops = ["0.5 w"]
    for i in range(len(rows) + 1 if ruled else 0):
        y = top - i * row_height
        ops.append(f"{left} {y} m {right} {y} l S")
    for j in range(cols + 1 if ruled else 0):
        x = left + j * col_width
        ops.append(f"{x} {top} m {x} {bottom} l S")
    for i, row in enumerate(rows):
        for j, text in enumerate(row):
            if text:
                x, y = left + j * col_width + 3, top - (i + 1) * row_height + 5
                ops.append(f"BT /F1 7 Tf {x} {y} Td ({_esc(str(text))}) Tj ET")
    return ops


def _esc(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
