"""Sent inside the ingest transaction after new SourceRecords are written, so the
archive can react without sources importing it (archive depends on sources)."""

from django.dispatch import Signal

records_committed = Signal()  # kwargs: source_file, records
