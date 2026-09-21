"""Synthetic two-supplier dataset with every trap pattern the archive must handle.

All values are invented. Supplier X uses one catalog header style, supplier Y another;
the rows are paired so that each trap appears at least once:

    strong          X-001 ~ Y-001  same OE, type, fitment, size (Y in GBP)
    wording         X-002 ~ Y-002  "Side Grille, Left side" vs "Left Side Grille"
    same size       X-003 Air Filter Housing vs X-004 Fan Shroud: equal size, same fitment
    same-source dup X-001 ~ X-005  one supplier, same product twice, X-005 has no OE
    no OE           X-005 ~ Y-008  type, fitment, size agree, no shared number
    OE, other type  X-006 Front Grille vs Y-003 Bug Screen, shared OE-SHR-0001
    name substring  X-007 Air Filter Housing vs Y-004 Air Filter Housing Cap, OE-SHR-0002
    OE, other side  X-008 Left vs Y-005 Right, shared OE-SHR-0003, same size
    in-file sides   Y-006 Left vs Y-007 Right, shared OE-TST-9010, Y-006 lacks years
    insufficient    X-011 ~ Y-010  same type, side, size; Y-010 has no fitment at all
                    X-011 ~ Y-006  same fitment and side; Y-006 has no years and no size
    side in column  Y-009 "Side Grille" named without side, Install Side = Right
    missing         X-009 no price or currency, X-010 no fitment or size,
                    Y-010 no fitment, Y-011 no MOQ
    currencies      X-002 EUR and X-003 USD cells both formatted "$"; Y-002 GBP
    short codes     X-01-00 and Y01X share "01" and must never be matched on it
"""

import datetime as dt
import functools

from .workbooks import HEADERS_A, HEADERS_B, workbook_bytes

VNL, CENTURY, VN = "Volvo VNL 2018-2023", "Freightliner Century", "Volvo VN 2004-2017"


def _d(day):
    return dt.datetime(2026, 8, day)


# Source Record ID, Supplier SKU, Product Description, Truck Application, Position,
# OE / Reference, Package Size, Unit Price, Currency, MOQ, Quote Date
ROWS_X = [
    ["X-001", "X-01-00", "Front Grille", VNL, None, "OE-TST-1001", "122 x 75 x 7 cm",
     42.67, "USD", 2, _d(3)],
    ["X-002", "X-02-L", "Side Grille, Left side", VNL, "Left", "OE-TST-1003", "86 x 36 x 56 cm",
     51.01, "EUR", 10, _d(5)],
    ["X-003", "X-03-00", "Air Filter Housing", CENTURY, None, "OE-TST-2003",
     "121 x 22 x 92 cm", 71.86, "USD", 1, _d(10)],
    ["X-004", "X-04-00", "Fan Shroud", CENTURY, None, "OE-TST-2005", "121 x 22 x 92 cm",
     80.2, "USD", 5, _d(12)],
    ["X-005", "X-05-00", "Front Grille", VNL, None, None, "122 x 75 x 7 cm",
     96.88, "USD", 5, _d(16)],
    ["X-006", "X-06-00", "Front Grille", VNL, None, "OE-SHR-0001", "122 x 75 x 7 cm",
     151.09, "EUR", 10, _d(11)],
    ["X-007", "X-07-00", "Air Filter Housing", CENTURY, None, "OE-SHR-0002",
     "121 x 22 x 92 cm", 159.43, "USD", 2, _d(13)],
    ["X-008", "X-08-L", "Side Grille, Left side", VNL, "Left", "OE-SHR-0003",
     "86 x 36 x 56 cm", 167.77, "USD", 10, _d(15)],
    ["X-009", "X-09-00", "Front Grille", CENTURY, None, None, "124 x 77 x 10 cm",
     None, None, 2, _d(17)],
    ["X-010", "X-10-00", "Fan Shroud", None, None, None, None, 184.45, "USD", 10, _d(19)],
    ["X-011", "X-11-L", "Left Side Grille", VN, "Left", None, "65 x 30 x 30 cm",
     142.75, "USD", 2, _d(9)],
]

# Source Ref, Brand Number, English Name, Fitment, Install Side, Cross Ref, Package,
# Offer Price, Curr., Min Order, Quoted On
ROWS_Y = [
    ["Y-001", "Y01X", "Front Grille", VNL, None, "OE-TST-1001", "122 x 75 x 7 cm",
     46.58, "GBP", 5, _d(3)],
    ["Y-002", "Y02L", "Left Side Grille", VNL, "Left", "OE-TST-1003", "86 x 36 x 56 cm",
     54.24, "USD", 20, _d(5)],
    ["Y-003", "Y03X", "Bug Screen", VNL, None, "OE-SHR-0001", "120 x 75 x 8 cm",
     149.99, "GBP", 1, _d(12)],
    ["Y-004", "Y04X", "Air Filter Housing Cap", CENTURY, None, "OE-SHR-0002",
     "32 x 32 x 8 cm", 157.65, "USD", 10, _d(14)],
    ["Y-005", "Y05R", "Right Side Grille", VNL, "Right", "OE-SHR-0003", "86 x 36 x 56 cm",
     165.31, "GBP", 1, _d(16)],
    ["Y-006", "Y06L", "Left Side Grille", "Volvo VN", "Left", "OE-TST-9010", None,
     88.71, "USD", 1, _d(14)],
    ["Y-007", "Y07R", "Right Side Grille", VN, "Right", "OE-TST-9010", "65 x 30 x 30 cm",
     92.54, "USD", 5, _d(15)],
    ["Y-008", "Y08X", "Front Grille", VNL, None, None, "122 x 75 x 7 cm",
     100.2, "USD", 20, _d(17)],
    ["Y-009", "Y09R", "Side Grille", VNL, "Right", "OE-TST-1004", "86 x 36 x 56 cm",
     58.07, "USD", 1, _d(6)],
    ["Y-010", "Y10L", "Left Side Grille", None, "Left", None, "65 x 30 x 30 cm",
     180.63, "GBP", 1, _d(2)],
    ["Y-011", "Y11X", "Air Filter Housing Cap", CENTURY, None, None, "32 x 32 x 8 cm",
     184.46, "USD", None, _d(3)],
]


@functools.cache  # one set of bytes per session: every save stamps a new time
def workbook_x() -> bytes:
    return workbook_bytes(HEADERS_A, ROWS_X, sheet="Price List")


@functools.cache
def workbook_y() -> bytes:
    return workbook_bytes(HEADERS_B, ROWS_Y, sheet="Catalog Export")


def ingest_both(user):
    """Archive, map (as suggested) and commit both suppliers' files; returns (x, y)."""
    from django.core.files.uploadedfile import SimpleUploadedFile

    from apps.sources.services import ingest, intake
    from apps.sources.services.storage import store_upload
    from apps.suppliers.tests.factories import SupplierFactory

    files = []
    for name, data in (("Supplier X", workbook_x()), ("Supplier Y", workbook_y())):
        source = store_upload(SimpleUploadedFile(f"{name}.xlsx", data),
                              SupplierFactory(name=name), user)
        intake.suggestions(source, intake.inspect(source))
        intake.confirm(source, {}, user)
        ingest.commit(source, user)
        files.append(source)
    return files
