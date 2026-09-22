"""archive_rematch --restandardize: vocabulary changes reach stored records as new
versions (docs/archive-design.html §10)."""

import json
from io import StringIO

import pytest
from django.core.management import CommandError, call_command

from apps.archive.models import Membership, ReviewItem
from apps.archive.services import review
from apps.sources.models import SourceRecord
from apps.sources.services import restandardize, standardize

from .conftest import find_item

pytestmark = pytest.mark.django_db


@pytest.fixture
def vocabulary(tmp_path, monkeypatch):
    """Edit a copy of the vocabulary: change(data) mutates it in place."""
    data = json.loads(standardize.VOCABULARY.read_text(encoding="utf-8"))
    path = tmp_path / "vocabulary.json"

    def change(edit):
        edit(data)
        data["version"] = "test"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        monkeypatch.setattr(standardize, "VOCABULARY", path)
        standardize.vocabulary.cache_clear()

    yield change
    standardize.vocabulary.cache_clear()


def rename_front_grille(data):
    data["part_types"]["Grille"] = data["part_types"].pop("Front Grille")


def add_cab_side_panel(data):
    """Catches Y-002 "Left Side Grille" but not X-002 "Side Grille, Left side"."""
    data["part_types"]["Cab Side Panel"] = {"aliases": ["left side grille"], "sided": True}


def run(*args) -> str:
    out = StringIO()
    call_command("archive_rematch", "--restandardize", *args, stdout=out, stderr=out)
    return out.getvalue()


def test_nothing_changes_with_the_same_rules(archive):
    assert restandardize.plan() == ([], [])


def test_a_dry_run_lists_changes_and_writes_nothing(archive, vocabulary):
    vocabulary(rename_front_grille)
    before = SourceRecord.objects.count()
    output = run()

    assert SourceRecord.objects.count() == before
    assert "X-001 v1" in output and "品类 Front Grille → Grille" in output
    assert "预演结束" in output


def test_commit_writes_new_versions_from_the_original(archive, vocabulary, user):
    vocabulary(rename_front_grille)
    reruns, _ = restandardize.plan()
    written = restandardize.commit(reruns, user)

    record = SourceRecord.objects.current().get(record_key="X-001")
    assert len(written) == len(reruns) > 0
    assert (record.version, record.change_type, record.part_type) == (2, "restandardize",
                                                                      "Grille")
    assert "规则重算（词表 test）" in record.note
    assert record.previous.part_type == "Front Grille"  # the old version is untouched
    assert record.raw == record.previous.raw
    assert restandardize.plan() == ([], [])  # idempotent


def test_a_rename_for_every_member_keeps_the_grouping(archive, vocabulary, user):
    review.confirm_same(find_item("X-001~Y-001"), user, "同一件")
    vocabulary(rename_front_grille)
    run("--commit")

    assert set(Membership.objects.filter(record_key__in=["X-001", "Y-001"])
               .values_list("status", flat=True)) == {"active"}
    assert not ReviewItem.objects.filter(kind="key_change")
    settled = find_item("X-001~Y-001", status="same")
    assert "规则重算后仍在同一产品" in settled.note


def test_a_change_that_splits_members_goes_to_review(archive, vocabulary, user):
    review.confirm_same(find_item("X-002~Y-002"), user, "同一件")
    vocabulary(add_cab_side_panel)
    run("--commit")

    assert Membership.objects.get(record_key="Y-002").status == "suspended"
    assert Membership.objects.get(record_key="X-002").status == "active"
    item = find_item("Y-002")
    assert item.kind == "key_change"
    assert "规则重算后关键字段变化" in item.triggers[0]
    assert "Side Grille → Cab Side Panel" in item.triggers[0]


def test_commit_needs_restandardize():
    with pytest.raises(CommandError):
        call_command("archive_rematch", "--commit")
