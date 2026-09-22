from . import matching, review


def on_records_committed(sender, *, source_file, records, user=None, **kwargs):
    """Runs inside the ingest transaction: new records get products, new versions move
    their membership forward (a key-field change suspends it for review), then
    matching runs. If anything fails, the whole ingest rolls back."""
    review.enroll([r for r in records if r.previous_id is None], source_file=source_file,
                  user=user)
    review.advance([r for r in records if r.previous_id], user=user)
    matching.rematch()
