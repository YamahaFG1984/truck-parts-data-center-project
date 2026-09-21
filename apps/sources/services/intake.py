"""From an archived file to a confirmed column mapping (steps 2–3 of §5)."""

from django.utils import timezone

from ..models import SourceFile
from . import mapping
from .readers import ReadError, Sheet, read_source


def inspect(source_file: SourceFile) -> list[Sheet]:
    """Read the file and record what was found; a failure is stored on the file
    (the original stays archived) and re-raised."""
    try:
        sheets = read_source(source_file)
    except ReadError as exc:
        source_file.status, source_file.error = SourceFile.Status.FAILED, str(exc)
        source_file.save(update_fields=["status", "error", "updated_at"])
        raise
    source_file.stats = source_file.stats | {"sheets": [
        {"name": s.name, "header_row": s.header_row, "rows": len(s.rows),
         "skipped": [{"row": r, "reason": why} for r, why in s.skipped]}
        for s in sheets
    ]}
    source_file.save(update_fields=["stats", "updated_at"])
    return sheets


def suggestions(source_file: SourceFile, sheets: list[Sheet], *, client=None) -> list[dict]:
    """Per sheet: {"name", "header_row", "columns": [suggestion + "samples"]}. Cached on the
    file until confirmed, so reloading the page does not ask the model again."""
    cached = source_file.mapping.get("sheets")
    if not cached:
        cached = [
            {"name": s.name, "header_row": s.header_row,
             "columns": mapping.suggest(s.headers, [r.texts() for r in s.rows],
                                        source_file.supplier, client=client)}
            for s in sheets
        ]
        source_file.mapping = {"sheets": cached, "confirmed": False}
        source_file.save(update_fields=["mapping", "updated_at"])
    samples = {s.name: s.rows[:mapping.SAMPLE_ROWS] for s in sheets}
    return [
        sheet | {"columns": [
            column | {"samples": [r.cells[column["header"]].text
                                  for r in samples.get(sheet["name"], [])
                                  if column["header"] in r.cells]}
            for column in sheet["columns"]
        ]}
        for sheet in cached
    ]


def confirm(source_file: SourceFile, chosen: dict[tuple[int, int], str], user):
    """Apply a person's choices; returns (errors, warnings). Nothing is saved on errors."""
    sheets = source_file.mapping["sheets"]
    errors, warnings = [], []
    for i, sheet in enumerate(sheets):
        for j, column in enumerate(sheet["columns"]):
            field = chosen.get((i, j), column["field"])
            if field != column["field"]:
                column.update(field=field, source="manual", confidence=1.0, reason="人工指定")
        sheet_errors, sheet_warnings = mapping.validate(sheet["columns"])
        prefix = f"工作表“{sheet['name']}”：" if len(sheets) > 1 else ""
        errors += [prefix + e for e in sheet_errors]
        warnings += [prefix + w for w in sheet_warnings]
    if errors:
        return errors, warnings
    for sheet in sheets:
        mapping.save_template(source_file.supplier, [c["header"] for c in sheet["columns"]],
                              sheet["columns"], user)
    source_file.mapping = {"sheets": sheets, "confirmed": True, "warnings": warnings,
                           "confirmed_by": user.pk, "confirmed_at": timezone.now().isoformat()}
    source_file.status = SourceFile.Status.MAPPED
    source_file.save(update_fields=["mapping", "status", "updated_at"])
    return errors, warnings
