"""Preview and first ingest of a mapped file (docs/archive-design.html §5 steps 4–6).

preview() never writes records. commit() writes them all in one transaction, or none.
Records whose identity the supplier already has are refused here; incremental import
with version comparison is M27.
"""

from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from ..models import RecordNumber, SourceFile, SourceRecord
from . import intake
from .standardize import LABELS, Standardized, standardize


class IngestError(ValueError):
    """Refused; the message is shown to the user."""


@dataclass
class Planned:
    sheet: str
    locator: str
    row_no: int
    page: int | None
    table_no: int | None
    raw: dict
    cells: dict
    std: Standardized
    record_key: str = ""
    key_kind: str = ""
    problem: str = ""  # blocks the commit

    @property
    def missing_labels(self) -> list[str]:
        return [LABELS.get(name, name) for name in self.std.missing]


def plan(source_file: SourceFile) -> list[Planned]:
    if not source_file.mapping.get("confirmed"):
        raise IngestError("列映射尚未确认，请先确认列映射。")
    columns = {s["name"]: s["columns"] for s in source_file.mapping["sheets"]}
    existing = set(SourceRecord.objects.filter(supplier=source_file.supplier)
                   .exclude(source_file=source_file).values_list("record_key", flat=True))
    planned, seen = [], {}
    for sheet in intake.inspect(source_file):
        if sheet.name not in columns:
            raise IngestError(f"“{sheet.name}”没有已确认的列映射，请重新确认映射。")
        for row in sheet.rows:
            item = Planned(
                sheet=sheet.name, row_no=row.row_no, page=row.page, table_no=row.table_no,
                locator=(f"P{row.page}/T{row.table_no}/R{row.row_no}" if row.page
                         else f"{sheet.name}!R{row.row_no}"),
                raw=row.texts(), cells={h: c.coord for h, c in row.cells.items()},
                std=standardize(row, columns[sheet.name]),
            )
            _identify(item, seen)
            if item.record_key in existing:
                item.problem = "该供应商已有同一身份的记录；增量导入（版本对比）在 M27 支持"
            planned.append(item)
    return planned


def preview(source_file: SourceFile) -> list[Planned]:
    planned = plan(source_file)
    source_file.stats = source_file.stats | {"preview": _counts(planned)}
    if source_file.status == SourceFile.Status.MAPPED:
        source_file.status = SourceFile.Status.PREVIEWED
    source_file.save(update_fields=["stats", "status", "updated_at"])
    return planned


def commit(source_file: SourceFile, user) -> int:
    if source_file.status == SourceFile.Status.COMMITTED:
        raise IngestError("这份资料已经入库。")
    planned = plan(source_file)
    blocked = [p for p in planned if p.problem]
    if blocked:
        raise IngestError(f"有 {len(blocked)} 行不能入库，例如 {blocked[0].locator}："
                          f"{blocked[0].problem}")
    with transaction.atomic():
        records = SourceRecord.objects.bulk_create([
            SourceRecord(
                source_file=source_file, supplier=source_file.supplier,
                record_key=p.record_key, key_kind=p.key_kind, locator=p.locator,
                sheet=p.sheet, page=p.page, table_no=p.table_no, row_no=p.row_no,
                raw=p.raw, cells=p.cells, fields=p.std.fields, warnings=p.std.warnings,
                missing=p.std.missing, content_hash=p.std.content_hash, **p.std.typed,
            )
            for p in planned
        ])
        RecordNumber.objects.bulk_create(
            number for record, p in zip(records, planned, strict=True)
            for number in _numbers(record, p.std)
        )
        source_file.status = SourceFile.Status.COMMITTED
        source_file.stats = source_file.stats | {"committed": _counts(planned) | {
            "by": user.pk, "at": timezone.now().isoformat()}}
        source_file.save(update_fields=["status", "stats", "updated_at"])
    return len(records)


def _identify(item: Planned, seen: dict) -> None:
    """record_key: source record ID, else supplier SKU, else a content hash."""
    record_id, sku = item.std.value("record_id"), item.std.typed["supplier_sku"]
    key, kind = ((record_id, SourceRecord.KeyKind.SOURCE_ID) if record_id else
                 (sku, SourceRecord.KeyKind.SUPPLIER_SKU) if sku else (None, None))
    duplicate = bool(key) and key in seen
    if duplicate:
        item.std.warnings.append(f"记录身份“{key}”与 {seen[key]} 重复，本行改用内容哈希识别")
    if duplicate or not key:
        if not duplicate:
            item.std.warnings.append("没有源记录 ID 和供应商料号，用内容哈希识别；"
                                     "以后无法识别这一条的更新")
        key, kind = f"#{item.std.content_hash[:32]}", SourceRecord.KeyKind.CONTENT
    seen.setdefault(key, item.locator)
    item.record_key, item.key_kind = key[:200], kind


def _numbers(record, std: Standardized):
    """One RecordNumber per (kind, normalized number); numbers with no letters or
    digits are skipped."""
    from apps.catalog.services.normalize import normalize_number

    seen = set()
    for kind, number in std.numbers:
        key = (kind, normalize_number(number))
        if key[1] and key not in seen:
            seen.add(key)
            yield RecordNumber(record=record, kind=kind, number=number[:100])


def _counts(planned: list[Planned]) -> dict:
    return {
        "rows": len(planned),
        "with_warnings": sum(1 for p in planned if p.std.warnings),
        "with_missing": sum(1 for p in planned if p.std.missing),
        "blocked": sum(1 for p in planned if p.problem),
    }
