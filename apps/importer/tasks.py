"""Background tasks for the importer app (run by django-q2 workers)."""

from apps.core.models import Job

from .models import ImportBatch
from .services.importing import ImportFailed, execute


def execute_batch(job_id: int, batch_id: int) -> dict:
    """Run one import. The import is a single transaction, so progress is reported
    at the end; a failure leaves nothing written and marks both job and batch."""
    job = Job.objects.get(pk=job_id)
    job.status = Job.Status.RUNNING
    job.save(update_fields=["status", "updated_at"])
    batch = ImportBatch.objects.get(pk=batch_id)
    try:
        counts = execute(batch).counts
    except ImportFailed as exc:
        job.status = Job.Status.FAILED
        job.failed = job.total
        job.note(str(exc))
        job.save(update_fields=["status", "failed", "message", "updated_at"])
        return {"error": str(exc)}
    job.status = Job.Status.DONE
    job.done = job.total
    job.note(f"新增 {counts['new']}，更新 {counts['updated']}，跳过 {counts['skipped']}，"
             f"疑似重复 {counts['duplicate']}，无效 {counts['invalid']}。")
    job.save(update_fields=["status", "done", "message", "updated_at"])
    return counts
