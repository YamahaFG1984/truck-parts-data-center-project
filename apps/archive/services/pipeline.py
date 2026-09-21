from . import matching, review


def on_records_committed(sender, *, source_file, records, user=None, **kwargs):
    """Runs inside the ingest transaction: new records get products, then matching
    runs. If anything fails, the whole ingest rolls back."""
    review.enroll(records, source_file=source_file, user=user)
    matching.rematch()
