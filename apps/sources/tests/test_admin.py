import pytest
from django.urls import reverse

from apps.sources.models import MappingTemplate, RecordNumber

from .conftest import make_record

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("model", ["sourcefile", "sourcerecord", "mappingtemplate"])
def test_changelists_open(admin_client, source_file, model):
    record = make_record(source_file)
    RecordNumber.objects.create(record=record, kind="oe", number="OE-1")
    MappingTemplate.objects.create(supplier=source_file.supplier, header_signature="s")

    assert admin_client.get(reverse(f"admin:sources_{model}_changelist")).status_code == 200


def test_records_can_be_viewed_but_not_added_or_changed(admin_client, source_file):
    record = make_record(source_file)
    RecordNumber.objects.create(record=record, kind="oe", number="OE-VNL-1001")
    change_url = reverse("admin:sources_sourcerecord_change", args=[record.pk])

    response = admin_client.get(change_url)
    assert response.status_code == 200
    assert "OEVNL1001" in response.content.decode()  # numbers shown inline
    assert admin_client.post(change_url, {"name": "x"}).status_code == 403
    assert admin_client.get(reverse("admin:sources_sourcerecord_add")).status_code == 403
