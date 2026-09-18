import datetime as dt
import pickle

import pytest
from django.urls import reverse
from django.utils import timezone
from django_q.models import OrmQ, Task

from apps.ai.llm.mock import MockClient
from apps.ai.models import AISuggestion
from apps.catalog.tests.factories import PartFactory
from apps.core.jobs import start_job, worker_missing
from apps.core.models import Job
from apps.importer import views as importer_views
from apps.importer.models import ImportBatch
from apps.importer.tests.test_import import make_batch, row

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _media_in_tmp(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"


def test_batch_enrich_runs_and_creates_one_suggestion_per_part(admin_client):
    parts = PartFactory.create_batch(3)

    response = admin_client.post(reverse("ai:enrich_batch"), {"parts": [p.pk for p in parts]})

    job = Job.objects.get()
    assert response.url == reverse("core:job", args=[job.pk])
    assert (job.status, job.total, job.done, job.failed, job.percent) == ("done", 3, 3, 0, 100)
    assert AISuggestion.objects.filter(status="pending").count() == 3
    assert Task.objects.filter(name=f"enrich-{job.pk}", success=True).exists()  # django-q ran it
    assert job.task_id


def test_one_failing_part_does_not_stop_the_batch(admin_client, monkeypatch):
    good, bad, also_good = PartFactory.create_batch(3)
    real = MockClient.extract_json

    def flaky(self, **kwargs):
        if kwargs["variables"]["sku"] == bad.sku:
            raise RuntimeError("model overloaded")
        return real(self, **kwargs)

    monkeypatch.setattr(MockClient, "extract_json", flaky)

    admin_client.post(reverse("ai:enrich_batch"), {"parts": [good.pk, bad.pk, also_good.pk]})

    job = Job.objects.get()
    assert (job.status, job.done, job.failed) == ("done", 2, 1)
    assert f"{bad.sku}：model overloaded" in job.message
    assert AISuggestion.objects.count() == 2


def test_batch_is_capped_and_ignores_unknown_ids(admin_client, monkeypatch):
    from apps.ai import views as ai_views

    monkeypatch.setattr(ai_views, "MAX_BATCH", 2)
    parts = PartFactory.create_batch(3)

    ids = [p.pk for p in parts] + ["999999", "x"]
    admin_client.post(reverse("ai:enrich_batch"), {"parts": ids})

    assert Job.objects.get().total == 2


def test_nothing_selected_sends_you_back(admin_client):
    response = admin_client.post(reverse("ai:enrich_batch"), {"next": "/parts/"}, follow=True)

    assert "请先勾选" in response.content.decode()
    assert not Job.objects.exists()


def test_task_arguments_are_plain_ids(admin_user):
    part = PartFactory()

    job = start_job(kind="enrich", title="t", func="apps.ai.tasks.enrich_parts", args=([part.pk],),
                    total=1, user=admin_user)

    args = Task.objects.get(name=f"enrich-{job.pk}").args
    assert args == (job.pk, [part.pk])
    pickle.dumps(args)  # nothing but ints and lists


def test_large_import_runs_in_the_background(admin_client, monkeypatch):
    monkeypatch.setattr(importer_views, "BACKGROUND_ROWS", 1)
    batch = make_batch([row(pn="HB-1", oe="20443906"), row(pn="HB-2", oe="20568713")])
    ImportBatch.objects.filter(pk=batch.pk).update(stats={"rows": 2})

    response = admin_client.post(reverse("importer:execute", args=[batch.pk]))

    job = Job.objects.get()
    assert response.url == reverse("core:job", args=[job.pk])
    assert (job.kind, job.status, job.done, job.total) == ("import", "done", 2, 2)
    assert "新增 2" in job.message
    assert job.result_url == reverse("importer:result", args=[batch.pk])
    batch.refresh_from_db()
    assert batch.status == "done"


def test_small_import_still_runs_inline(admin_client):
    batch = make_batch([row()])
    ImportBatch.objects.filter(pk=batch.pk).update(stats={"rows": 1})

    response = admin_client.post(reverse("importer:execute", args=[batch.pk]))

    assert response.url == reverse("importer:result", args=[batch.pk])
    assert not Job.objects.exists()


# --- progress page -----------------------------------------------------------------------------


def test_progress_fragment_polls_while_running_and_stops_when_done(admin_client, admin_user):
    job = Job.objects.create(kind="enrich", title="t", total=4, done=1, status="running",
                             created_by=admin_user)
    url = reverse("core:job", args=[job.pk])

    running = admin_client.get(url, HTTP_HX_REQUEST="true").content.decode()
    Job.objects.filter(pk=job.pk).update(status="done", done=4, result_url="/ai/review/")
    finished = admin_client.get(url, HTTP_HX_REQUEST="true").content.decode()

    assert 'hx-trigger="every 2s"' in running and "1 / 4" in running and "<html" not in running
    assert 'hx-trigger' not in finished and "查看结果" in finished


def test_page_warns_when_no_worker_picks_the_job_up(admin_client, admin_user):
    job = Job.objects.create(kind="enrich", title="t", total=1, created_by=admin_user)
    Job.objects.filter(pk=job.pk).update(created_at=timezone.now() - dt.timedelta(seconds=30))
    # What enqueue() really writes: lock = the enqueue time, i.e. in the past by now.
    enqueued = timezone.now() - dt.timedelta(seconds=30)
    OrmQ.objects.create(key="tpdc", payload="queued", lock=enqueued)

    body = admin_client.get(reverse("core:job", args=[job.pk])).content.decode()

    assert "后台任务未运行" in body and "qcluster" in body
    assert 'hx-trigger="every 2s"' in body  # keeps polling: starting a worker resumes it


def test_no_warning_while_fresh_or_once_a_worker_claimed_the_queue(admin_user):
    job = Job.objects.create(kind="enrich", title="t", total=1, created_by=admin_user)
    OrmQ.objects.create(key="tpdc", payload="queued", lock=timezone.now())
    assert not worker_missing(job)  # younger than 10 s

    Job.objects.filter(pk=job.pk).update(created_at=timezone.now() - dt.timedelta(seconds=30))
    # dequeue() pushes the lock into the future while a worker runs the item
    OrmQ.objects.update(lock=timezone.now() + dt.timedelta(seconds=300))
    job.refresh_from_db()
    assert not worker_missing(job)


def test_part_list_has_selection_form(admin_client):
    PartFactory()

    body = admin_client.get(reverse("catalog:part_list")).content.decode()

    assert reverse("ai:enrich_batch") in body and 'name="parts"' in body


def test_worker_check_matches_what_the_real_broker_writes(admin_user):
    """Enqueue through django-q itself (not a hand-made row) with no worker running."""
    from django_q.conf import Conf

    Conf.SYNC = False
    try:
        job = start_job(kind="enrich", title="t", func="apps.ai.tasks.enrich_parts",
                        args=([],), total=0, user=admin_user)
    finally:
        Conf.SYNC = True
    Job.objects.filter(pk=job.pk).update(created_at=timezone.now() - dt.timedelta(seconds=30))
    job.refresh_from_db()

    assert job.status == "queued" and OrmQ.objects.count() == 1
    assert worker_missing(job)
