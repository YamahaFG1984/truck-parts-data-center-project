"""Write the synthetic phase-2 sample files into a directory (all values invented).

    python scripts/make_archive_samples.py demo-output/samples

01/02 are the two suppliers' price lists the archive tests use (every trap pattern);
03-05 are "unfamiliar" files for the rehearsal in docs/DEMO_SCRIPT.md:

    03_supplier_z_offer.xlsx    new supplier, a title row above the headers, headers the
                                synonym table does not know (Item Code, L/R), sizes in mm
    04_supplier_w_catalog.pdf   a ruled table in a PDF, one more supplier
    05_supplier_x_update.xlsx   supplier X's next edition: a price, a position and an
                                SKU change, one row dropped, one row added
"""

import datetime as dt
import io
import sys
from pathlib import Path

from openpyxl import Workbook

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

VNL, CENTURY = "Volvo VNL 2018-2023", "Freightliner Century"

Z_HEADERS = ["Item Code", "Part Description", "Vehicle", "L/R", "OEM No.", "Carton Size (mm)",
             "FOB Price", "Ccy", "Min Qty", "Valid From"]
Z_ROWS = [
    ["Z-100", "Front Grille Assy", VNL, None, "OE-TST-1001", "1220 x 750 x 70", 44.1, "USD", 3],
    ["Z-101", "Side Grille RH", VNL, "R", "OE-TST-1004", "860 x 360 x 560", 57.0, "EUR", 5],
    ["Z-102", "Fan Shroud", CENTURY, None, "OE-TST-2005", "1210 x 220 x 920", 79.5, "USD", 2],
    ["Z-103", "Bug Screen", VNL, None, "OE-SHR-0001", "1200 x 750 x 80", 148.0, "GBP", 1],
    ["Z-104", "Headlamp Assembly LH", "Kenworth T680 2014-2021", "L", "OE-TST-7001",
     "700 x 400 x 350", 210.0, "USD", 4],
    ["Z-105", "Door Mirror", None, "L", None, None, None, None, 10],
]

W_HEADERS = ["Line No", "Part No", "Description", "Fitment", "OE No", "Price", "Curr"]
W_ROWS = [
    ["W-1", "W100", "Front Grille", VNL, "OE-TST-1001", "39.90", "USD"],
    ["W-2", "W200", "Air Filter Housing", CENTURY, "OE-TST-2003", "69.00", "USD"],
    ["W-3", "W300", "Left Side Grille", "Volvo VN 2004-2017", "-", "140.00", "USD"],
    ["W-4", "W400", "Hood", "Peterbilt 579 2013-2020", "OE-TST-8001", "", ""],
]


def supplier_z() -> bytes:
    book = Workbook()
    sheet = book.active
    sheet.title = "Offer"
    sheet["A1"] = "Supplier Z Price Offer - synthetic demo data"
    sheet.append([])
    sheet.append(Z_HEADERS)
    for row in Z_ROWS:
        sheet.append([*row, dt.datetime(2026, 9, 1)])
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def main(directory: str) -> list[Path]:
    from apps.sources.tests.dataset import workbook_x, workbook_x2, workbook_y
    from apps.sources.tests.pdfgen import make_pdf

    out = Path(directory)
    out.mkdir(parents=True, exist_ok=True)
    files = {
        "01_supplier_x.xlsx": workbook_x(),
        "02_supplier_y.xlsx": workbook_y(),
        "03_supplier_z_offer.xlsx": supplier_z(),
        "04_supplier_w_catalog.pdf": make_pdf([[W_HEADERS, *W_ROWS]], col_width=80),
        "05_supplier_x_update.xlsx": workbook_x2(),
    }
    paths = []
    for name, data in files.items():
        path = out / name
        path.write_bytes(data)
        paths.append(path)
    return paths


if __name__ == "__main__":
    for written in main(sys.argv[1] if len(sys.argv) > 1 else "demo-output/samples"):
        print(written)
