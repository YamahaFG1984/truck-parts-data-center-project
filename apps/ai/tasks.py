"""Background tasks for the ai app (run by django-q2 workers)."""

from apps.catalog.models import Part
from apps.core.models import Job

from .services.enrich import enrich_part


def enrich_parts(job_id: int, part_ids: list[int]) -> dict:
    """Create a suggestion for each part. One part failing never stops the others."""
    job = Job.objects.get(pk=job_id)
    job.status = Job.Status.RUNNING
    job.save(update_fields=["status", "updated_at"])
    parts = Part.objects.select_related("category").prefetch_related("numbers", "fitments")
    for part_id in part_ids:
        part = parts.filter(pk=part_id).first()
        try:
            if part is None:
                raise LookupError("产品已不存在")
            enrich_part(part)
        except Exception as exc:  # any single failure is recorded, the batch goes on
            job.failed += 1
            job.note(f"{part.sku if part else part_id}：{exc}")
        else:
            job.done += 1
        job.save(update_fields=["done", "failed", "message", "updated_at"])
    job.status = Job.Status.DONE
    job.note(f"完成 {job.done} 个，失败 {job.failed} 个。")
    job.save(update_fields=["status", "message", "updated_at"])
    return {"done": job.done, "failed": job.failed}
