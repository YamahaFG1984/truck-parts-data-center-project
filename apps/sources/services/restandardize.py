"""Re-derive the standardized fields of current records after the rules change
(docs/archive-design.html §10, M28).

Records are immutable, so a different result becomes a new version (change type
"restandardize"), read again from the archived original with the column mapping that
was confirmed for it. Rows whose result is unchanged are not written. The content hash
covers the cell texts only, so the derived fields (with their own warnings) and the
missing list are compared. The archive
treats the new versions like any other: a key-field change suspends the membership
and waits for a person.
"""

import json
from collections import defaultdict
from dataclasses import dataclass

from django.db import transaction

from ..models import RecordNumber, SourceRecord
from ..signals import records_committed
from . import versions
from .ingest import locator_of, numbers_of
from .readers import ReadError, read_source
from .standardize import Standardized, standardize, vocabulary


@dataclass
class Rerun:
    record: SourceRecord
    std: Standardized
    changes: list  # versions.diff entries; empty when only rules, sources or warnings moved


def plan(supplier=None) -> tuple[list[Rerun], list[str]]:
    """(records whose result would change, problems). Writes nothing."""
    vocabulary.cache_clear()
    current = (SourceRecord.objects.current().select_related("source_file", "supplier")
               .prefetch_related("numbers").order_by("source_file_id", "id"))
    if supplier is not None:
        current = current.filter(supplier=supplier)
    by_file = defaultdict(dict)
    for record in current:
        by_file[record.source_file][record.locator] = record
    reruns, problems = [], []
    for source, records in by_file.items():
        columns = {s["name"]: s["columns"] for s in source.mapping.get("sheets", [])}
        try:
            sheets = read_source(source)
        except ReadError as exc:
            problems.append(f"{source.original_name}：无法重新读取（{exc}）")
            continue
        found = set()
        for sheet in sheets:
            for row in sheet.rows:
                record = records.get(locator_of(sheet.name, row))
                if record is None or sheet.name not in columns:
                    continue
                found.add(record.locator)
                std = standardize(row, columns[sheet.name])
                if not _differs(record, std):
                    continue
                _, changes = versions.diff(versions.snapshot_record(record),
                                           versions.snapshot_standardized(std))
                reruns.append(Rerun(record, std, changes))
        problems += [f"{source.original_name} {locator}：原件中找不到这一行，未重算"
                     for locator in sorted(records.keys() - found)]
    return reruns, problems


def commit(reruns: list[Rerun], user=None) -> list[SourceRecord]:
    """Write the new versions, one records_committed per source file."""
    rules = f"词表 {vocabulary().get('version', '?')}"
    by_file = defaultdict(list)
    for rerun in reruns:
        by_file[rerun.record.source_file].append(rerun)
    written = []
    with transaction.atomic():  # every new version first, then the archive reacts per file
        batches = []
        for source, group in by_file.items():
            records = SourceRecord.objects.bulk_create([
                SourceRecord(
                    source_file=source, supplier=r.record.supplier,
                    record_key=r.record.record_key, key_kind=r.record.key_kind,
                    locator=r.record.locator, sheet=r.record.sheet, page=r.record.page,
                    table_no=r.record.table_no, row_no=r.record.row_no,
                    version=r.record.version + 1, previous=r.record,
                    change_type=SourceRecord.ChangeType.RESTANDARDIZE,
                    note=_note(rules, r.changes),
                    raw=r.record.raw, cells=r.record.cells, fields=r.std.fields,
                    warnings=r.std.warnings, missing=r.std.missing,
                    content_hash=r.std.content_hash, **r.std.typed,
                )
                for r in group
            ])
            RecordNumber.objects.bulk_create(
                number for record, r in zip(records, group, strict=True)
                for number in numbers_of(record, r.std))
            batches.append((source, records))
            written += records
        for source, records in batches:
            records_committed.send(sender=SourceRecord, source_file=source, records=records,
                                   user=user)
    return written


def _note(rules: str, changes: list) -> str:
    return f"规则重算（{rules}）：{versions.summary(changes) or '字段出处或警告变化'}"[:200]


def _differs(record: SourceRecord, std: Standardized) -> bool:
    def canon(value):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)

    # The record-level warnings list is the fields' own warnings prefixed with labels:
    # a relabelled prefix alone is wording, not a new version.
    return any(canon(a) != canon(b) for a, b in (
        (record.fields, std.fields), (record.missing, std.missing)))
