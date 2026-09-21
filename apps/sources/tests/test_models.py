import pytest
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError

from apps.sources.models import ImmutableRecord, MappingTemplate, RecordNumber, SourceRecord

from .conftest import make_record

pytestmark = pytest.mark.django_db


def _integrity_error(fn):
    with pytest.raises(IntegrityError), transaction.atomic():
        fn()


def test_a_written_record_cannot_be_changed(source_file):
    record = make_record(source_file)
    record.name = "changed"

    with pytest.raises(ImmutableRecord):
        record.save()
    with pytest.raises(ImmutableRecord):
        SourceRecord.objects.filter(pk=record.pk).update(name="changed")

    record.refresh_from_db()
    assert record.name == ""


def test_a_written_record_cannot_be_deleted(source_file):
    record = make_record(source_file)

    with pytest.raises(ImmutableRecord):
        record.delete()
    with pytest.raises(ImmutableRecord):
        SourceRecord.objects.all().delete()
    assert SourceRecord.objects.filter(pk=record.pk).exists()


def test_the_source_file_is_kept_while_records_point_at_it(source_file):
    make_record(source_file)

    with pytest.raises(ProtectedError):
        source_file.delete()


def test_one_locator_per_file(source_file):
    make_record(source_file, row_no=2)

    _integrity_error(lambda: make_record(source_file, row_no=2, record_key="other"))


def test_versions_form_a_single_chain(source_file):
    v1 = make_record(source_file, row_no=2)
    v2 = make_record(source_file, row_no=3, record_key=v1.record_key, version=2, previous=v1,
                     change_type=SourceRecord.ChangeType.PRICE_UPDATE)

    assert list(SourceRecord.objects.current()) == [v2]
    assert v1.next_version == v2
    # A second successor of v1 would fork the history.
    _integrity_error(lambda: make_record(source_file, row_no=4, record_key=v1.record_key,
                                         version=2, previous=v1))


def test_a_later_version_must_be_numbered_above_one(source_file):
    v1 = make_record(source_file, row_no=2)

    _integrity_error(lambda: make_record(source_file, row_no=3, previous=v1, version=1))


def test_record_numbers_are_normalized(source_file):
    record = make_record(source_file)
    RecordNumber.objects.create(record=record, kind="oe", number=" oe-vnl 1001 ")
    RecordNumber.objects.bulk_create([RecordNumber(record=record, kind="supplier_sku",
                                                   number="A-01-00")])

    assert sorted(record.numbers.values_list("number", "number_norm")) == [
        ("A-01-00", "A0100"), ("oe-vnl 1001", "OEVNL1001")]


def test_a_number_without_letters_or_digits_is_refused(source_file):
    record = make_record(source_file)

    _integrity_error(lambda: RecordNumber.objects.create(record=record, kind="oe", number="--"))


def test_one_mapping_template_per_supplier_and_header_set(supplier):
    MappingTemplate.objects.create(supplier=supplier, header_signature="abc", headers=["A"])

    _integrity_error(lambda: MappingTemplate.objects.create(supplier=supplier,
                                                            header_signature="abc"))
