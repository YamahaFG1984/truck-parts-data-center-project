"""Preview and ingest of a mapped file (docs/archive-design.html §5 steps 4–6, §10).

preview() never writes records. Each row is compared with the supplier's current
version of the same record: new, unchanged, quote update, other update or key-field
change, with a field-level diff; records the supplier sent before but not this time
are listed. commit() writes new records and new versions in one transaction (old
versions stay untouched) and sends records_committed inside it, so the archive's
work is part of the same transaction.
"""

from dataclasses import dataclass, field

from django.db import transaction
from django.utils import timezone

from ..models import RecordNumber, SourceFile, SourceRecord
from ..signals import records_committed
from . import intake, versions
from .standardize import LABELS, Standardized, standardize

UNCHANGED = "unchanged"
CHANGE_LABELS = {"new": "新增", UNCHANGED: "未变", "price_update": "报价更新",
                 "info_update": "资料更新", "key_change": "关键字段变化"}


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
    change: str = "new"
    previous: SourceRecord | None = None
    diff: list = field(default_factory=list)
    problem: str = ""  # blocks the commit

    @property
    def missing_labels(self) -> list[str]:
        return [LABELS.get(name, name) for name in self.std.missing]

    @property
    def change_label(self) -> str:
        return CHANGE_LABELS[self.change]


@dataclass
class Plan:
    rows: list[Planned]
    absent: list[SourceRecord]  # sent before, not in this file: shown, never deleted

    def __iter__(self):
        return iter(self.rows)

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, index):
        return self.rows[index]

    def counts(self) -> dict:
        counts = {c: 0 for c in CHANGE_LABELS}
        for row in self.rows:
            counts[row.change] += 1
        return counts | {
            "rows": len(self.rows), "absent": len(self.absent),
            "with_warnings": sum(1 for p in self.rows if p.std.warnings),
            "with_missing": sum(1 for p in self.rows if p.std.missing),
            "blocked": sum(1 for p in self.rows if p.problem),
        }


def plan(source_file: SourceFile) -> Plan:
    if not source_file.mapping.get("confirmed"):
        raise IngestError("列映射尚未确认，请先确认列映射。")
    columns = {s["name"]: s["columns"] for s in source_file.mapping["sheets"]}
    current = {r.record_key: r for r in SourceRecord.objects.current()
               .filter(supplier=source_file.supplier).exclude(source_file=source_file)
               .prefetch_related("numbers")}
    rows, seen = [], {}
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
            _compare(item, current.get(item.record_key))
            rows.append(item)
    absent = [r for key, r in sorted(current.items()) if key not in seen]
    return Plan(rows, absent)


def preview(source_file: SourceFile) -> Plan:
    planned = plan(source_file)
    source_file.stats = source_file.stats | {"preview": planned.counts()}
    if source_file.status == SourceFile.Status.MAPPED:
        source_file.status = SourceFile.Status.PREVIEWED
    source_file.save(update_fields=["stats", "status", "updated_at"])
    return planned


def commit(source_file: SourceFile, user) -> int:
    """Write new records and new versions; returns how many were written."""
    if source_file.status == SourceFile.Status.COMMITTED:
        raise IngestError("这份资料已经入库。")
    planned = plan(source_file)
    blocked = [p for p in planned if p.problem]
    if blocked:
        raise IngestError(f"有 {len(blocked)} 行不能入库，例如 {blocked[0].locator}："
                          f"{blocked[0].problem}")
    written = [p for p in planned if p.change != UNCHANGED]
    with transaction.atomic():
        records = SourceRecord.objects.bulk_create([
            SourceRecord(
                source_file=source_file, supplier=source_file.supplier,
                record_key=p.record_key, key_kind=p.key_kind, locator=p.locator,
                sheet=p.sheet, page=p.page, table_no=p.table_no, row_no=p.row_no,
                version=p.previous.version + 1 if p.previous else 1, previous=p.previous,
                change_type=p.change, raw=p.raw, cells=p.cells, fields=p.std.fields,
                warnings=p.std.warnings, missing=p.std.missing,
                content_hash=p.std.content_hash, **p.std.typed,
            )
            for p in written
        ])
        RecordNumber.objects.bulk_create(
            number for record, p in zip(records, written, strict=True)
            for number in _numbers(record, p.std)
        )
        source_file.status = SourceFile.Status.COMMITTED
        source_file.stats = source_file.stats | {"committed": planned.counts() | {
            "written": len(records), "by": user.pk, "at": timezone.now().isoformat()}}
        source_file.save(update_fields=["status", "stats", "updated_at"])
        records_committed.send(sender=SourceFile, source_file=source_file, records=records,
                               user=user)
    return len(records)


def _compare(item: Planned, previous: SourceRecord | None) -> None:
    if previous is None:
        return
    item.previous = previous
    if previous.content_hash == item.std.content_hash:
        item.change = UNCHANGED
        return
    change, changes = versions.diff(versions.snapshot_record(previous),
                                    versions.snapshot_standardized(item.std))
    item.change, item.diff = change or "info_update", changes


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
