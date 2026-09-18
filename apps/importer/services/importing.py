"""Dry-run and transactional import of a mapped batch (docs/architecture.html §7.5, fig. A4).

dry_run() and execute() share one planner, so the dry-run report is exactly what
execute() will do. execute() re-plans inside one transaction.atomic(): any
exception rolls back every row and marks the batch failed.

Per row: build a Record from the mapped columns -> identify the part (SKU, then
OE / cross numbers, then the supplier's part number) -> decide new / updated /
skipped / duplicate / invalid. Update rules: fill blanks; overwrite only when
the batch asks for it and the part is not verified; existing numbers are never
changed, only added to.
"""

import datetime as dt
import re
from dataclasses import dataclass, field
from decimal import Decimal

from django.conf import settings
from django.db import transaction

from apps.catalog.models import Brand, Category, Fitment, Part, PartNumber
from apps.catalog.services.normalize import (
    brand_hint,
    canonical_brand,
    normalize_number,
    split_numbers,
)
from apps.catalog.services.quality import recompute
from apps.suppliers.models import SupplierOffer

from ..models import ImportBatch, ImportRow
from . import parsing
from .loader import read_table

OEM_BRANDS = {"Volvo", "Renault Trucks", "Scania", "Mercedes-Benz", "MAN", "DAF", "Iveco",
              "Sinotruk HOWO", "Shacman", "FAW", "Dongfeng", "Weichai", "Cummins", "Freightliner",
              "Kenworth", "Peterbilt", "International"}
AFTERMARKET_BRANDS = {"Knorr-Bremse", "WABCO", "Bosch", "MANN-FILTER", "Fleetguard", "Donaldson",
                      "Sachs"}
UNCATEGORIZED_CODE = "GEN"
_CJK = re.compile(r"[\u3400-\u9fff]+")
_LATIN = re.compile(r"[A-Za-z]")
TEXT_FIELDS = {"name_en": "英文品名", "name_zh": "中文品名", "description_en": "英文描述"}
RESULTS = [r.value for r in ImportRow.Result]


class ImportFailed(Exception):
    pass


@dataclass
class Record:
    sku: str = ""
    numbers: list[tuple[str, str, str | None, float]] = field(default_factory=list)
    supplier_pn: str = ""
    texts: dict[str, str] = field(default_factory=dict)
    category: str = ""
    fitments: list[dict] = field(default_factory=list)
    unit_cost: Decimal | None = None
    currency: str | None = None
    price_term: str = "FOB"
    moq: int | None = None
    lead_days: int | None = None
    packaging: dict = field(default_factory=dict)
    confidence: float = 1.0
    problems: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def norms(self) -> list[str]:
        return [normalize_number(n) for n, *_ in self.numbers]


@dataclass
class RowPlan:
    row_no: int
    raw: dict
    result: str
    message: str
    record: Record | None = None
    part: Part | None = None
    new_sku: str = ""


@dataclass
class ImportReport:
    plans: list[RowPlan]

    @property
    def counts(self) -> dict[str, int]:
        counts = dict.fromkeys(RESULTS, 0)
        for plan in self.plans:
            counts[plan.result] += 1
        return counts


# --- public API ---------------------------------------------------------------------------


def dry_run(batch: ImportBatch) -> ImportReport:
    """Plan every row without writing catalog data; store the counts on the batch."""
    report = ImportReport(_Planner(batch).plan(_read(batch)))
    batch.stats = batch.stats | {"dry_run": report.counts}
    batch.status = ImportBatch.Status.VALIDATED
    batch.save(update_fields=["stats", "status", "updated_at"])
    return report


def execute(batch: ImportBatch) -> ImportReport:
    """Import in one transaction; on any error nothing is written and the batch is failed."""
    table = _read(batch)
    try:
        with transaction.atomic():
            planner = _Planner(batch)
            report = ImportReport(planner.plan(table))
            touched = []
            for plan in report.plans:
                if plan.result in (ImportRow.Result.NEW, ImportRow.Result.UPDATED):
                    plan.part = planner.apply(plan)
                    touched.append(plan.part.pk)
            ImportRow.objects.bulk_create([
                ImportRow(batch=batch, row_no=p.row_no, raw=p.raw, result=p.result,
                          message=p.message, part=p.part)
                for p in report.plans
            ])
            recompute(Part.objects.filter(pk__in=touched))
            batch.stats = batch.stats | {"result": report.counts}
            batch.status = ImportBatch.Status.DONE
            batch.error = ""
            batch.save(update_fields=["stats", "status", "error", "updated_at"])
    except Exception as exc:
        batch.status = ImportBatch.Status.FAILED
        batch.error = f"{type(exc).__name__}: {exc}"[:2000]
        batch.save(update_fields=["status", "error", "updated_at"])
        raise ImportFailed(f"导入失败，已全部回滚：{exc}") from exc
    return report


def _read(batch: ImportBatch):
    with batch.file.open("rb") as fh:
        return read_table(fh, batch.original_name)


# --- row -> Record --------------------------------------------------------------------------


def build_record(row: dict, columns: list[dict]) -> Record:
    rec = Record()
    vehicles, model, engine, years, number_brand = [], "", "", (None, None), None
    for column in columns:
        header, target = column["header"], column["field"]
        value = parsing.clean(row.get(header, ""))
        if not value or target == "ignore":
            continue
        rec.confidence = min(rec.confidence, float(column.get("confidence", 1.0)))
        if target in ("oe_number", "cross_number"):
            _add_numbers(rec, value, header, "OE" if target == "oe_number" else "CROSS",
                         float(column.get("confidence", 1.0)))
        elif target == "sku":
            rec.sku = rec.sku or value.upper()
        elif target == "supplier_pn":
            rec.supplier_pn = rec.supplier_pn or value
        elif target == "name_en" and _CJK.search(value) and _LATIN.search(value):
            # "减震器 Shock Absorber": split by script (data dictionary §10 #12)
            rec.texts.setdefault("name_zh", " ".join(_CJK.findall(value))[:200])
            rec.texts.setdefault("name_en", " ".join(_CJK.sub(" ", value).split())[:200])
        elif target in TEXT_FIELDS:
            rec.texts.setdefault(target, value if target == "description_en" else value[:200])
        elif target == "category":
            rec.category = rec.category or value
        elif target == "brand":
            number_brand = number_brand or canonical_brand(value) or value
        elif target == "make":
            vehicles += parsing.parse_vehicles(value)
        elif target == "model":
            model = model or value
        elif target == "engine":
            engine = engine or value
        elif target == "year_from":
            years = parsing.parse_years(value)
        elif target == "year_to":
            years = (years[0], parsing.parse_years(value)[0])
        elif target == "unit_cost":
            rec.unit_cost = parsing.parse_decimal(value)
            rec.currency = rec.currency or parsing.detect_currency(value, header)
            rec.price_term = next((t for t in ("EXW", "CIF") if t.lower() in header.lower()), "FOB")
        elif target == "currency":
            rec.currency = parsing.detect_currency(value) or value.upper()
        elif target == "moq":
            rec.moq = parsing.parse_int(value)
        elif target == "lead_days":
            rec.lead_days = parsing.parse_lead_days(value)
        elif target in ("gross_weight_kg", "net_weight_kg"):  # "12.5KGS", "500g" or "12"
            weight = parsing.parse_packing(value).get("gross_weight_kg")
            weight = weight if weight is not None else parsing.parse_decimal(value)
            if weight:
                rec.packaging.setdefault(target, float(weight))
        elif target in ("pcs_per_carton", "carton_l_cm", "carton_w_cm", "carton_h_cm"):
            for key, parsed in parsing.parse_packing(value).items():
                rec.packaging.setdefault(key, parsed)
        elif target == "image_url":
            rec.notes.append("图片链接暂不自动下载")
    if rec.unit_cost is not None and rec.currency is None:
        rec.currency = "USD"
    for make, vehicle_model in vehicles or ([("", "")] if model else []):
        if make:
            rec.fitments.append({"make": make, "model": vehicle_model or model, "engine": engine,
                                 "year_from": years[0], "year_to": years[1]})
    # An OE number belongs to the truck maker: take the brand column, else the vehicle make.
    oe_brand = number_brand or next(
        (f["make"] for f in rec.fitments if f["make"] in OEM_BRANDS), None
    )
    rec.numbers = [
        (number, kind, brand or (oe_brand if kind == "OE" else None), conf)
        for number, kind, brand, conf in rec.numbers
    ]
    return rec


def _add_numbers(rec: Record, value: str, header: str, kind: str, confidence: float):
    for number in split_numbers(value):
        if parsing.looks_scientific(number):
            rec.problems.append(
                f"“{header}”列的 {number} 被 Excel 转成了科学计数，原编号已丢失，"
                "请把该列设为文本后重新导出"
            )
            continue
        hints = brand_hint(number)
        aftermarket = [h for h in hints if h in AFTERMARKET_BRANDS]
        brand = aftermarket[0] if len(aftermarket) == 1 and len(hints) == 1 else None
        kind_used = kind
        if kind == "OE" and hints and len(aftermarket) == len(hints):
            # An aftermarket-format number in the OE column is really a cross reference.
            kind_used, confidence = "CROSS", 0.6
        rec.numbers.append((number.strip(), kind_used, brand, confidence))


# --- planning and applying ---------------------------------------------------------------------


class _Planner:
    def __init__(self, batch: ImportBatch):
        self.batch = batch
        self.columns = batch.column_mapping.get("columns", [])
        self.overwrite = bool(batch.column_mapping.get("overwrite"))
        self.today = dt.date.today()
        self.brands = {b.name.lower(): b for b in Brand.objects.all()}
        self.categories = {}
        for c in Category.objects.order_by("parent_id"):  # leaves (with a parent) win
            for name in (c.name, c.name_en):
                if name:
                    self.categories[name.lower()] = c
        self.next_number: dict[str, int] = {}

    # planning ----------------------------------------------------------------------------

    def plan(self, table) -> list[RowPlan]:
        records = [build_record(row, self.columns) for row in table.rows]
        self._load_indexes(records)
        plans, claimed = [], {}
        for row_no, raw, rec in zip(table.row_numbers, table.rows, records, strict=True):
            plans.append(self._plan_row(row_no, raw, rec, claimed))
        return plans

    def _load_indexes(self, records: list[Record]) -> None:
        norms = {n for rec in records for n in rec.norms}
        self.norm_index: dict[str, set[int]] = {}
        for norm, part_id in PartNumber.objects.filter(
            number_norm__in=norms, kind__in=["OE", "CROSS"]
        ).values_list("number_norm", "part_id"):
            self.norm_index.setdefault(norm, set()).add(part_id)
        skus = {rec.sku for rec in records if rec.sku}
        sku_ids = dict(Part.objects.filter(sku__in=skus).values_list("sku", "pk"))
        self.supplier_pns = {}
        if self.batch.supplier_id:
            pns = {rec.supplier_pn for rec in records if rec.supplier_pn}
            self.supplier_pns = {
                normalize_number(pn): part_id
                for pn, part_id in SupplierOffer.objects.filter(
                    supplier_id=self.batch.supplier_id, supplier_pn__in=pns
                ).values_list("supplier_pn", "part_id")
            }
        ids = set(sku_ids.values()) | {i for ids in self.norm_index.values() for i in ids}
        ids |= set(self.supplier_pns.values())
        self.parts = Part.objects.select_related("category").prefetch_related(
            "numbers", "fitments"
        ).in_bulk(ids)
        self.sku_ids = sku_ids
        self.offers = {
            o.part_id: o for o in SupplierOffer.objects.filter(
                supplier_id=self.batch.supplier_id, part_id__in=ids, quoted_at=self.today
            )
        } if self.batch.supplier_id else {}

    def _plan_row(self, row_no, raw, rec: Record, claimed: dict) -> RowPlan:
        def plan(result, message, **kw):
            return RowPlan(row_no, raw, result, message, record=rec, **kw)

        if rec.problems:
            return plan("invalid", "；".join(rec.problems))
        # Decision tree A4: a row needs a SKU, an OE number or a supplier part number;
        # a cross reference alone does not say which of our parts it is.
        has_oe = any(kind == "OE" for _, kind, _, _ in rec.numbers)
        if not (rec.sku or has_oe or rec.supplier_pn):
            return plan("invalid", "缺少 SKU、OE 号和供应商料号，无法判断是哪个产品")
        if not (rec.sku or has_oe) and not self.batch.supplier_id:
            return plan("invalid", "只有供应商料号但没有选择供应商，无法判断是哪个产品")

        for norm in rec.norms:  # an earlier row of this file already takes this number
            if norm in claimed:
                return plan("skipped", f"与第 {claimed[norm]} 行是同一产品（{norm}），已按第 "
                                       f"{claimed[norm]} 行导入")

        part_ids = set()
        if rec.sku and rec.sku in self.sku_ids:
            part_ids = {self.sku_ids[rec.sku]}
        else:
            for norm in rec.norms:
                part_ids |= self.norm_index.get(norm, set())
            if not part_ids and rec.supplier_pn:
                pn_part = self.supplier_pns.get(normalize_number(rec.supplier_pn))
                part_ids = {pn_part} if pn_part else set()
        if len(part_ids) > 1:
            skus = "、".join(sorted(self.parts[i].sku for i in part_ids))
            return plan("duplicate", f"编号已挂在 {skus} 上，疑似重复，未导入（请先在看板中处理）")

        for norm in rec.norms:
            claimed[norm] = row_no
        notes = self._notes(rec)
        if part_ids:
            part = self.parts[part_ids.pop()]
            changes = self._changes(part, rec)
            if not changes:
                return plan("skipped", "库中已有且信息一致，无需更新" + notes, part=part)
            return plan("updated", f"{part.sku} 补充：{'、'.join(changes)}" + notes, part=part)
        sku = rec.sku or self._allocate_sku(rec)
        return plan("new", f"新建草稿产品 {sku}" + notes, new_sku=sku)

    def _notes(self, rec: Record) -> str:
        notes = list(rec.notes)
        if rec.unit_cost is not None and not self.batch.supplier_id:
            notes.append("未选择供应商，价格未导入")
        elif rec.unit_cost is not None and rec.currency != "USD":
            notes.append(f"价格币种为 {rec.currency}，需要汇率，未导入")
        elif rec.unit_cost is not None and rec.unit_cost <= 0:
            notes.append("价格为 0，未导入")
        return f"（{'；'.join(notes)}）" if notes else ""

    def _offer_values(self, rec: Record) -> dict | None:
        if not (self.batch.supplier_id and rec.unit_cost and rec.unit_cost > 0
                and rec.currency == "USD"):
            return None
        return {"supplier_pn": rec.supplier_pn[:64], "unit_cost_usd": rec.unit_cost.quantize(
            Decimal("0.01")), "moq": rec.moq or None, "lead_days": rec.lead_days,
            "price_term": rec.price_term}

    def _changes(self, part: Part, rec: Record) -> list[str]:
        changes = []
        for key, label in TEXT_FIELDS.items():
            if self._should_set(part, getattr(part, key), rec.texts.get(key)):
                changes.append(label)
        category = self.categories.get(rec.category.lower()) if rec.category else None
        if category and self._should_set(part, part.category_id, category.pk):
            changes.append("分类")
        existing = {(n.number_norm, n.kind) for n in part.numbers.all()}
        added = [
            n for n in self._number_rows(rec) if (normalize_number(n[0]), n[1]) not in existing
        ]
        if added:
            changes.append(f"{len(added)} 个编号")
        fits = {self._fit_key(f.__dict__) for f in part.fitments.all()}
        new_fits = [f for f in rec.fitments if self._fit_key(f) not in fits]
        if new_fits:
            changes.append(f"{len(new_fits)} 条适配")
        if any(self._should_set(part, part.packaging.get(k), v) for k, v in rec.packaging.items()):
            changes.append("包装")
        offer = self._offer_values(rec)
        current = self.offers.get(part.pk)
        if offer and (not current or any(getattr(current, k) != v for k, v in offer.items())):
            changes.append("报价")
        return changes

    def _should_set(self, part: Part, current, new) -> bool:
        if new in (None, ""):
            return False
        if current in (None, ""):
            return True
        return self.overwrite and not part.verified and current != new

    def _number_rows(self, rec: Record) -> list[tuple[str, str, str | None, float]]:
        rows = list(rec.numbers)
        if rec.supplier_pn and self.batch.supplier_id:
            rows.append((rec.supplier_pn, "SUPPLIER", None, rec.confidence))
        return rows

    @staticmethod
    def _fit_key(f: dict) -> tuple:
        return (f["make"].lower(), (f.get("model") or "").lower(), (f.get("engine") or "").lower(),
                f.get("year_from") or 0, f.get("year_to") or 0)

    def _allocate_sku(self, rec: Record) -> str:
        category = self.categories.get(rec.category.lower()) if rec.category else None
        code = (category.code if category and category.code else UNCATEGORIZED_CODE).upper()
        prefix = f"{settings.COMPANY_SKU_PREFIX}{code}-"
        if prefix not in self.next_number:
            existing = Part.objects.filter(sku__startswith=prefix).values_list("sku", flat=True)
            numbers = [int(s[len(prefix):]) for s in existing if s[len(prefix):].isdigit()]
            self.next_number[prefix] = max(numbers, default=0) + 1
        sku = f"{prefix}{self.next_number[prefix]:05d}"
        self.next_number[prefix] += 1
        return sku

    # applying ------------------------------------------------------------------------------

    def apply(self, plan: RowPlan) -> Part:
        rec = plan.record
        category = self.categories.get(rec.category.lower()) if rec.category else None
        part = plan.part
        if part is None:
            part = Part.objects.create(
                sku=plan.new_sku, category=category, packaging=rec.packaging,
                source="import", confidence=Decimal(str(round(rec.confidence, 2))),
                **rec.texts,
            )
            existing_numbers, existing_fits = set(), set()
        else:
            dirty = []
            for key in TEXT_FIELDS:
                if self._should_set(part, getattr(part, key), rec.texts.get(key)):
                    setattr(part, key, rec.texts[key])
                    dirty.append(key)
            if category and self._should_set(part, part.category_id, category.pk):
                part.category = category
                dirty.append("category")
            packaging = dict(part.packaging)
            for key, value in rec.packaging.items():
                if self._should_set(part, packaging.get(key), value):
                    packaging[key] = value
            if packaging != part.packaging:
                part.packaging = packaging
                dirty.append("packaging")
            if dirty:
                part.save(update_fields=[*dirty, "updated_at"])
            existing_numbers = {(n.number_norm, n.kind) for n in part.numbers.all()}
            existing_fits = {self._fit_key(f.__dict__) for f in part.fitments.all()}

        new_numbers = []
        for number, kind, brand_name, confidence in self._number_rows(rec):
            key = (normalize_number(number), kind)
            if key in existing_numbers:
                continue
            existing_numbers.add(key)
            new_numbers.append(PartNumber(
                part=part, number=number[:64], kind=kind, brand=self._brand(brand_name),
                source="import", confidence=Decimal(str(round(confidence, 2))),
            ))
        PartNumber.objects.bulk_create(new_numbers)
        for fit in rec.fitments:
            if self._fit_key(fit) not in existing_fits:
                existing_fits.add(self._fit_key(fit))
                Fitment.objects.create(part=part, source="import", **fit)
        offer = self._offer_values(rec)
        if offer:
            SupplierOffer.objects.update_or_create(
                supplier_id=self.batch.supplier_id, part=part, quoted_at=self.today,
                defaults=offer | {"notes": f"导入批次 #{self.batch.pk}"},
            )
        return part

    def _brand(self, name: str | None) -> Brand | None:
        if not name:
            return None
        brand = self.brands.get(name.lower())
        if brand is None:
            kind = Brand.Kind.OEM if name in OEM_BRANDS else Brand.Kind.AFTERMARKET
            brand = Brand.objects.create(name=name, kind=kind)
            self.brands[name.lower()] = brand
        return brand
