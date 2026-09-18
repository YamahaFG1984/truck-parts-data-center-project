"""Synthetic suppliers and quotes for the demo catalog (docs/data-dictionary.html §12).

Fictional companies; about 75% of parts get 1–3 quotes from suppliers that make
that kind of part. Every quote also records the supplier's own part number as a
PartNumber(kind=SUPPLIER), as the data dictionary §7 requires.
"""

import datetime as dt
import random
from decimal import Decimal

from apps.catalog.models import Part, PartNumber

from .models import Supplier, SupplierOffer

ALL = None  # generalist: quotes any category
# name, supplier number prefix, category codes (None = all), rating
SUPPLIERS = [
    ("Hebei Demo Brake Co., Ltd.", "HB", ["BPD", "BDS", "BCH"], 4),
    ("Ruian Demo Filter Factory", "RF", ["AFL", "OFL", "FFL"], 4),
    ("Shiyan Demo Auto Parts Co.", "SY", ALL, 3),
    ("Jinan Demo Truck Parts Co.", "JN", ALL, 3),
    ("Wenzhou Demo Electric Co.", "WZ", ["HLP", "MIR"], 4),
    ("Hangzhou Demo Driveline Co.", "HZ", ["CLD", "SHK", "WPM", "TRB"], 5),
]
COST_RANGE = {  # USD per unit, by category code
    "BPD": (12, 45), "BDS": (45, 140), "BCH": (30, 90), "AFL": (15, 60), "OFL": (5, 18),
    "FFL": (6, 25), "CLD": (60, 180), "SHK": (25, 80), "WPM": (40, 150), "HLP": (35, 120),
    "MIR": (25, 90), "TRB": (180, 600),
}
FIRST_QUOTE = dt.date(2026, 6, 1)


def reset_suppliers() -> None:
    """Run after the catalog reset: offers cascade with parts, suppliers are PROTECTed."""
    SupplierOffer.objects.all().delete()
    Supplier.objects.all().delete()


def seed_offers(seed: int, share: float = 0.75) -> int:
    rng = random.Random(seed + 2)
    suppliers = [
        (Supplier.objects.create(name=name, rating=rating, contact=f"sales@{prefix.lower()}.demo",
                                 notes="演示用虚构供应商"), prefix, codes)
        for name, prefix, codes, rating in SUPPLIERS
    ]
    offers, numbers = [], []
    for part in Part.objects.order_by("sku"):
        code = part.sku.split("-")[1]
        if rng.random() >= share or code not in COST_RANGE:
            continue
        eligible = [s for s in suppliers if s[2] is ALL or code in s[2]]
        base = rng.uniform(*COST_RANGE[code])
        k = min(len(eligible), rng.choice([1, 1, 2, 2, 3]))  # same RNG call order as before
        for supplier, prefix, _ in rng.sample(eligible, k=k):
            quoted = FIRST_QUOTE + dt.timedelta(days=rng.randint(0, 100))
            supplier_pn = f"{prefix}-{rng.randint(1000, 9999)}"
            offers.append(SupplierOffer(
                supplier=supplier, part=part, supplier_pn=supplier_pn,
                unit_cost_usd=Decimal(str(round(base * rng.uniform(0.9, 1.15), 2))),
                moq=rng.choice([10, 20, 50, 100, 200]),
                lead_days=rng.choice([15, 20, 25, 30, 35, 45]),
                price_term=rng.choices(["FOB", "EXW", "CIF"], [0.7, 0.2, 0.1])[0],
                quoted_at=quoted,
                valid_until=quoted + dt.timedelta(days=90) if rng.random() < 0.7 else None,
            ))
            numbers.append(PartNumber(part=part, number=supplier_pn, kind="SUPPLIER",
                                      source="import"))
    SupplierOffer.objects.bulk_create(offers)
    PartNumber.objects.bulk_create(numbers)
    return len(offers)
