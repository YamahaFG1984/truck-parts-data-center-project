"""Start and watch background jobs (django-q2, ORM broker).

Task functions receive only primitive ids (never model instances), so they can be
pickled into the queue and re-read fresh inside the worker.
"""

import datetime as dt

from django.utils import timezone
from django_q.models import OrmQ
from django_q.tasks import async_task

from .models import Job

# A job still queued this long, with unclaimed items on the queue, means no
# qcluster process is picking work up.
STALL_AFTER = dt.timedelta(seconds=10)


def start_job(*, kind: str, title: str, func: str, args: tuple, total: int, user,
              result_url: str = "") -> Job:
    job = Job.objects.create(kind=kind, title=title[:200], total=total, created_by=user,
                             result_url=result_url)
    task_id = async_task(func, job.pk, *args, task_name=f"{kind}-{job.pk}")
    # With sync=True (tests) the task has already run: update only the id column so
    # the progress it wrote is not overwritten by this stale object.
    Job.objects.filter(pk=job.pk).update(task_id=task_id or "")
    job.refresh_from_db()
    return job


def worker_missing(job: Job) -> bool:
    """True when the job still waits and the queue holds items no worker has taken.

    django-q2's ORM broker sets OrmQ.lock to "now" on enqueue; a worker takes items
    whose lock is in the past and pushes it into the future while running them.
    So an item with a lock in the past is sitting there unclaimed.
    """
    if job.status != Job.Status.QUEUED:
        return False
    now = timezone.now()
    if now - job.created_at < STALL_AFTER:
        return False
    return OrmQ.objects.filter(lock__lt=now).exists()
