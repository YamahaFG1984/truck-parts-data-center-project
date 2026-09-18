"""Synthetic demo catalog (docs/data-dictionary.html §12).

Everything here is invented: numbers follow each brand's *format* (§9) but are
random and do not identify real parts. A fixed seed makes every run identical.
Dirty data (separators, full-width, lowercase, gaps, duplicate OEs) is injected
on purpose so the quality dashboard and cleaning features have work to show.
"""

import random
from dataclasses import dataclass, field
from io import BytesIO

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from PIL import Image, ImageDraw, ImageFont

from .models import Brand, Category, Fitment, Part, PartImage, PartNumber

DEFAULT_SEED = 20260918

# --- Categories (§6) -------------------------------------------------------------


def _num(key, label, unit="mm", required=False):
    return {"key": key, "label": label, "type": "number", "unit": unit, "required": required}


def _enum(key, label, options, required=False):
    return {"key": key, "label": label, "type": "enum", "options": options, "required": required}


def _text(key, label, required=False):
    return {"key": key, "label": label, "type": "string", "required": required}


def _bool(key, label):
    return {"key": key, "label": label, "type": "bool", "required": False}


SIDE = ["LH", "RH"]
# (parent zh, parent en), leaf zh, leaf en, code, name variants, fields, aftermarket brands
CATEGORIES = [
    (("制动系统", "Brake"), "刹车片", "Brake Pad Set", "BPD", ["Front Axle", "Rear Axle"],
     [_num("length_mm", "长度", required=True), _num("width_mm", "宽度", required=True),
      _num("thickness_mm", "厚度", required=True),
      _enum("friction_material", "摩擦材料", ["semi-metallic", "ceramic", "organic"]),
      _bool("wear_sensor", "磨损传感器")], ["Knorr-Bremse", "Meritor"]),
    (("制动系统", "Brake"), "刹车盘", "Brake Disc", "BDS", ["Front Axle", "Rear Axle"],
     [_num("outer_diameter_mm", "外径", required=True), _num("thickness_mm", "厚度", required=True),
      _num("bolt_holes", "螺栓孔数", unit="", required=True), _num("min_thickness_mm", "最小厚度")],
     ["Knorr-Bremse", "Meritor"]),
    (("制动系统", "Brake"), "制动气室", "Spring Brake Chamber", "BCH", ["T24/30", "T30/30"],
     [_enum("type", "型号", ["T16", "T20", "T24", "T30", "T24/30", "T30/30"], required=True),
      _num("stroke_mm", "行程", required=True), _text("mounting", "安装方式")],
     ["WABCO", "Knorr-Bremse"]),
    (("滤清器", "Filter"), "空气滤清器", "Air Filter", "AFL", ["Primary", "Safety"],
     [_num("outer_diameter_mm", "外径", required=True), _num("height_mm", "高度", required=True),
      _num("inner_diameter_mm", "内径")], ["MANN-FILTER", "Donaldson", "Fleetguard"]),
    (("滤清器", "Filter"), "机油滤清器", "Oil Filter", "OFL", ["Spin-on", "Cartridge"],
     [_text("thread", "螺纹", required=True), _num("outer_diameter_mm", "外径", required=True),
      _num("height_mm", "高度", required=True), _bool("bypass_valve", "旁通阀")],
     ["MANN-FILTER", "Fleetguard", "Donaldson"]),
    (("滤清器", "Filter"), "燃油滤清器", "Fuel Filter", "FFL", ["with Water Separator", "Fine"],
     [_text("thread", "螺纹", required=True), _num("outer_diameter_mm", "外径", required=True),
      _num("height_mm", "高度", required=True), _bool("water_separator", "油水分离")],
     ["MANN-FILTER", "Fleetguard", "Bosch"]),
    (("传动系统", "Driveline"), "离合器片", "Clutch Disc", "CLD", ["430 mm", "400 mm"],
     [_num("outer_diameter_mm", "外径", required=True), _num("spline_teeth", "花键齿数", unit="",
      required=True), _num("spline_diameter_mm", "花键直径", required=True),
      _enum("facing_material", "摩擦片材料", ["organic", "ceramic"])], ["Sachs"]),
    (("悬挂系统", "Suspension"), "减震器", "Shock Absorber", "SHK", ["Front", "Rear", "Cab"],
     [_num("extended_length_mm", "伸长长度", required=True),
      _num("compressed_length_mm", "压缩长度", required=True),
      _text("mounting_top", "上安装", required=True),
      _text("mounting_bottom", "下安装", required=True)],
     ["Sachs"]),
    (("冷却系统", "Cooling"), "水泵", "Water Pump", "WPM", ["with Gasket", "without Pulley"],
     [_num("impeller_diameter_mm", "叶轮直径", required=True),
      _num("bolt_holes", "螺栓孔数", unit="", required=True), _bool("with_gasket", "含垫片")],
     ["Bosch"]),
    (("电气系统", "Electrical"), "前大灯", "Headlamp", "HLP", ["LH", "RH"],
     [_enum("side", "左右", SIDE, required=True), _enum("voltage", "电压", ["12V", "24V"],
      required=True), _text("bulb_type", "灯泡型号")], ["Bosch"]),
    (("发动机件", "Engine"), "涡轮增压器", "Turbocharger", "TRB", ["Complete", "Core Assembly"],
     [_text("turbo_model", "增压器型号", required=True), _bool("with_actuator", "含执行器")], []),
    (("车身件", "Body"), "后视镜", "Main Mirror", "MIR", ["LH, Heated", "RH, Heated", "LH", "RH"],
     [_enum("side", "左右", SIDE, required=True), _bool("heated", "加热"),
      _bool("electric", "电动")],
     []),
]
ENGINE_PARTS = {"OFL", "FFL", "WPM", "TRB"}

# --- Brands, number formats (§9), vehicles -----------------------------------------


def _digits(rng, n):
    return "".join(rng.choice("0123456789") for _ in range(n))


NUMBER_FORMATS = {
    "Volvo": lambda r: "2" + _digits(r, 7),
    "Renault Trucks": lambda r: "50" + _digits(r, 8),
    "Scania": lambda r: "1" + _digits(r, 6),
    "Mercedes-Benz": lambda r: f"A {_digits(r, 3)} {_digits(r, 3)} {_digits(r, 2)} {_digits(r, 2)}",
    "MAN": lambda r: f"81.{_digits(r, 5)}-{_digits(r, 4)}",
    "DAF": lambda r: r.choice("12") + _digits(r, 6),
    "Iveco": lambda r: "50" + _digits(r, 7),
    "Sinotruk HOWO": lambda r: r.choice(["WG", "VG", "AZ"]) + _digits(r, 10),
    "Shacman": lambda r: "DZ" + _digits(r, 10),
    "Cummins": lambda r: r.choice("34") + _digits(r, 6),
    "Knorr-Bremse": lambda r: "K" + _digits(r, 6),
    "WABCO": lambda r: r.choice("49") + _digits(r, 9),
    "Bosch": lambda r: f"0 986 {_digits(r, 3)} {_digits(r, 3)}",
    "MANN-FILTER": lambda r: f"{r.choice(['W', 'WK', 'C'])} {_digits(r, 3)}/{r.randint(1, 40)}",
    "Fleetguard": lambda r: r.choice(["FF", "LF", "AF"]) + _digits(r, 4),
    "Donaldson": lambda r: "P" + _digits(r, 6),
    "Sachs": lambda r: f"3{_digits(r, 3)} {_digits(r, 3)} {_digits(r, 3)}",
    "Meritor": lambda r: "MDP" + _digits(r, 4),
}
OEM_BRANDS = ["Volvo", "Renault Trucks", "Scania", "Mercedes-Benz", "MAN", "DAF", "Iveco",
              "Sinotruk HOWO", "Shacman", "Cummins"]
AFTERMARKET_BRANDS = ["Knorr-Bremse", "WABCO", "Bosch", "MANN-FILTER", "Fleetguard",
                      "Donaldson", "Sachs", "Meritor"]

# make -> (share of parts, [(model, engine)])
VEHICLES = {
    "Volvo": (0.40, [("FH12", "D12"), ("FH16", "D16"), ("FM", "D13"), ("FMX", "D13")]),
    "Scania": (0.10, [("R-series", "DC13"), ("P-series", "DC9"), ("G-series", "DC13")]),
    "Mercedes-Benz": (0.10, [("Actros", "OM501"), ("Axor", "OM457"), ("Atego", "OM924")]),
    "MAN": (0.10, [("TGA", "D2066"), ("TGX", "D2676"), ("TGS", "D2066")]),
    "DAF": (0.08, [("XF105", "MX-13"), ("XF106", "MX-13"), ("CF85", "PACCAR MX")]),
    "Renault Trucks": (0.06, [("Magnum", "DXi13"), ("Premium", "DXi11"), ("T", "DTI13")]),
    "Iveco": (0.06, [("Stralis", "Cursor 13"), ("Trakker", "Cursor 13"), ("Eurocargo", "Tector")]),
    "Sinotruk HOWO": (0.06, [("A7", "WD615"), ("T7H", "MC11"), ("HOWO-7", "WD615")]),
    "Shacman": (0.04, [("F3000", "WP10"), ("X3000", "WP12"), ("H3000", "WP10")]),
}

# --- Dirty-format helpers (§10) -------------------------------------------------------


def to_fullwidth(text: str) -> str:
    return "".join(
        "　" if ch == " " else chr(ord(ch) + 0xFEE0) if "!" <= ch <= "~" else ch
        for ch in text
    )


def add_separators(text: str, rng: random.Random) -> str:
    """"20443906" -> "2044-3906" or "20 443 906"; already separated numbers get hyphens."""
    if not text.isalnum():
        return text.replace(" ", "-")
    cut = len(text) // 2
    return f"{text[:cut]}-{text[cut:]}" if rng.random() < 0.5 else " ".join(
        [text[:2], text[2:5], text[5:]]
    )


class NumberFactory:
    """Brand-formatted random numbers that never collide unless asked to."""

    def __init__(self, rng: random.Random, taken: set[str] | None = None):
        self.rng = rng
        self.taken = taken if taken is not None else set()

    def new(self, brand: str) -> str:
        from .services.normalize import normalize_number

        while True:
            number = NUMBER_FORMATS[brand](self.rng)
            norm = normalize_number(number)
            if norm not in self.taken:
                self.taken.add(norm)
                return number

    def dirty(self, number: str) -> str:
        """Injected dirt: ~20% extra separators, ~5% full-width, ~5% lowercase overall.

        Only about a fifth of numbers contain letters, so those are lowercased at 25%.
        """
        if any(ch.isalpha() for ch in number) and self.rng.random() < 0.25:
            return number.lower()
        roll = self.rng.random()
        if roll < 0.20:
            return add_separators(number, self.rng)
        if roll < 0.25:
            return to_fullwidth(number)
        return number


# --- Placeholder images -----------------------------------------------------------------


def placeholder_jpeg(title: str, sku: str, hue: int) -> bytes:
    image = Image.new("RGB", (800, 600), (40 + hue % 60, 70 + hue % 90, 110 + hue % 100))
    draw = ImageDraw.Draw(image)
    draw.rectangle([30, 30, 770, 570], outline=(255, 255, 255), width=4)
    draw.text((400, 250), title, fill="white", anchor="mm", font=ImageFont.load_default(56))
    draw.text((400, 340), sku, fill="white", anchor="mm", font=ImageFont.load_default(40))
    draw.text((400, 520), "DEMO · NOT A REAL PART", fill=(220, 220, 220), anchor="mm",
              font=ImageFont.load_default(24))
    buf = BytesIO()
    image.save(buf, "JPEG", quality=80)
    return buf.getvalue()


# --- The seeder ----------------------------------------------------------------------------


@dataclass
class SeedResult:
    parts: int = 0
    numbers: int = 0
    fitments: int = 0
    images: int = 0
    duplicate_groups: int = 0
    samples: list[dict] = field(default_factory=list)  # parts the supplier Excel repeats
    taken_norms: set[str] = field(default_factory=set)


def reset_catalog() -> None:
    """Delete every catalog row and the image files they point to."""
    for image in PartImage.objects.all():
        image.image.delete(save=False)
    Part.objects.all().delete()
    Category.objects.filter(parent__isnull=False).delete()
    Category.objects.all().delete()
    Brand.objects.all().delete()


def seed_catalog(parts: int = 400, seed: int = DEFAULT_SEED) -> SeedResult:
    rng = random.Random(seed)
    numbers = NumberFactory(rng)
    result = SeedResult(taken_norms=numbers.taken)

    brands = {name: Brand.objects.create(name=name, kind=Brand.Kind.OEM) for name in OEM_BRANDS}
    brands |= {
        name: Brand.objects.create(name=name, kind=Brand.Kind.AFTERMARKET)
        for name in AFTERMARKET_BRANDS
    }
    parents, leaves = {}, []
    for (pzh, pen), zh, en, code, variants, fields, aftermarket in CATEGORIES:
        if pzh not in parents:
            parents[pzh] = Category.objects.create(name=pzh, name_en=pen)
        leaf = Category.objects.create(
            name=zh, name_en=en, code=code, parent=parents[pzh], attribute_schema={"fields": fields}
        )
        leaves.append((leaf, variants, aftermarket))

    makes = list(VEHICLES)
    weights = [VEHICLES[m][0] for m in makes]
    oe_numbers: list[tuple[Part, PartNumber]] = []
    vehicle_of: dict[int, str] = {}
    counters: dict[str, int] = {}

    for index in range(parts):
        leaf, variants, aftermarket = rng.choice(leaves)
        make = rng.choices(makes, weights)[0]
        model, engine = rng.choice(VEHICLES[make][1])
        variant = rng.choice(variants)
        counters[leaf.code] = counters.get(leaf.code, 0) + 1
        sku = f"FIT-{leaf.code}-{counters[leaf.code]:05d}"

        part = Part.objects.create(
            sku=sku,
            name_en=f"{leaf.name_en}, {variant}",
            name_zh=f"{leaf.name}（{variant}）",
            category=leaf if rng.random() >= 0.20 else None,
            attributes=_attributes(leaf.schema, rng) if rng.random() < 0.85 else {},
            description_en=_description(leaf.name_en, variant, make, model)
            if rng.random() >= 0.15 else "",
            keywords=[f"{make} {leaf.name_en}".lower(), f"{model} {leaf.name_en}".lower()],
            packaging=_packaging(rng) if rng.random() < 0.70 else {},
            status=rng.choices(["draft", "reviewed", "published"], [0.6, 0.3, 0.1])[0],
            source="import" if rng.random() < 0.8 else "manual",
        )
        result.parts += 1
        vehicle_of[part.pk] = f"{make} {model}"

        rows = []
        if rng.random() >= 0.25:  # 75% have an OE number
            for _ in range(rng.choice([1, 1, 2, 3])):
                rows.append((numbers.new(make), "OE", make))
            if make == "Volvo":  # Renault sells the same part as 74 + Volvo number
                renault = "74" + rows[0][0]
                numbers.taken.add(renault)
                rows.append((renault, "CROSS", "Renault Trucks"))
            if leaf.code in ENGINE_PARTS and rng.random() < 0.25:
                rows.append((numbers.new("Cummins"), "OE", "Cummins"))
        # 10 of 12 categories have aftermarket brands; 0.48 gives ~40% of all parts.
        if aftermarket and rng.random() < 0.48:
            for brand in rng.sample(aftermarket, k=min(len(aftermarket), rng.choice([1, 2]))):
                rows.append((numbers.new(brand), "CROSS", brand))
        created = PartNumber.objects.bulk_create(
            [
                PartNumber(part=part, number=numbers.dirty(n), kind=k, brand=brands[b],
                           source=part.source)
                for n, k, b in rows
            ]
        )
        result.numbers += len(created)
        oe_numbers += [(part, pn) for pn in created if pn.kind == "OE"]

        if rng.random() < 0.70:
            chosen = rng.sample(VEHICLES[make][1], k=min(len(VEHICLES[make][1]), rng.randint(1, 3)))
            for fit_model, fit_engine in chosen:
                year_from = rng.randint(1993, 2016)
                Fitment.objects.create(
                    part=part, make=make, model=fit_model, engine=fit_engine,
                    year_from=year_from,
                    year_to=None if rng.random() < 0.2 else year_from + rng.randint(4, 12),
                    source=part.source,
                )
                result.fitments += 1

        if rng.random() < 0.65:
            for n in range(1 if rng.random() < 0.85 else 2):
                path = f"parts/{sku}/demo-{n + 1}.jpg"
                if default_storage.exists(path):
                    default_storage.delete(path)
                data = placeholder_jpeg(leaf.name_en, sku, hue=index * 37)
                saved = default_storage.save(path, ContentFile(data))
                PartImage.objects.create(part=part, image=saved, is_primary=(n == 0))
                result.images += 1

    result.samples = [
        {"oe": pn.number, "name_en": p.name_en, "vehicle": vehicle_of[p.pk]}
        for p, pn in rng.sample(oe_numbers, k=min(12, len(oe_numbers)))
    ]
    result.duplicate_groups = _make_duplicates(oe_numbers, rng, groups=10)
    return result


def _make_duplicates(oe_numbers, rng, groups: int) -> int:
    """Copy an OE number onto a second, unrelated part: the "suspected duplicate" case."""
    made = 0
    pool = oe_numbers[:]
    rng.shuffle(pool)
    while made < groups and len(pool) >= 2:
        (source_part, pn), (other_part, _) = pool.pop(), pool.pop()
        if source_part.pk == other_part.pk:
            continue
        PartNumber.objects.create(part=other_part, number=pn.number, kind="OE", brand=pn.brand,
                                  source="import")
        made += 1
    return made


def _attributes(schema, rng) -> dict:
    values = {}
    for f in schema.fields:
        if not f.required and rng.random() < 0.5:
            continue
        if f.type == "number":
            values[f.key] = rng.randint(4, 40) if f.unit == "" else rng.randint(20, 480)
        elif f.type == "enum":
            values[f.key] = rng.choice(f.options)
        elif f.type == "bool":
            values[f.key] = rng.random() < 0.5
        else:
            values[f.key] = rng.choice(["M22x1.5", "3/4-16 UNF", "eye", "pin", "HX55", "GT4082"])
    required = [f.key for f in schema.fields if f.required]
    if required and rng.random() < 0.35:  # incomplete specs for the dashboard
        values.pop(rng.choice(required), None)
    return values


def _packaging(rng) -> dict:
    return {
        "unit": rng.choice(["pc", "set", "pair"]),
        "pcs_per_carton": rng.choice([1, 2, 4, 10, 20]),
        "carton_l_cm": rng.randint(20, 60),
        "carton_w_cm": rng.randint(15, 40),
        "carton_h_cm": rng.randint(10, 35),
        "gross_weight_kg": round(rng.uniform(0.5, 25), 1),
    }


def _description(name: str, variant: str, make: str, model: str) -> str:
    return (
        f"{name} ({variant}) for {make} {model} heavy trucks. Manufactured to OE specifications "
        f"and 100% inspected before shipment. Please confirm the OE number or send a photo "
        f"before ordering to ensure fitment. Demo data: not a real product."
    )
