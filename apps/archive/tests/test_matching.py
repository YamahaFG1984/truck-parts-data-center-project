import hashlib

import pytest
from django.core.management import call_command

from apps.archive.models import Membership, Product, ReviewItem
from apps.archive.services import matching
from apps.sources.models import SourceRecord

pytestmark = pytest.mark.django_db


def open_items():
    """{"X-001~Y-001": item} for pairs, {"X-009": item} for single records."""
    def short(identity):
        return identity.split(":", 1)[1]

    return {"~".join(sorted(filter(None, [short(i.identity_a), short(i.identity_b or ":")]))): i
            for i in ReviewItem.objects.filter(status="open")}


EXPECTED = {
    "X-001~Y-001": "strong",
    "X-002~Y-002": "strong",  # different wording and currency
    "X-006~Y-003": "number_conflict",  # Front Grille vs Bug Screen
    "X-007~Y-004": "number_conflict",  # Housing vs Housing Cap
    "X-008~Y-005": "position_conflict",
    "Y-006~Y-007": "position_conflict",  # inside one supplier's file
    "X-001~X-005": "same_source",
    "X-005~X-006": "same_source",
    "Y-001~Y-008": "same_source",
    "Y-004~Y-011": "same_source",
    "X-001~Y-008": "no_number",
    "X-005~Y-001": "no_number",
    "X-005~Y-008": "no_number",
    "X-006~Y-008": "no_number",
    "X-011~Y-006": "insufficient",  # Y-006 has no years and no size
    "X-011~Y-010": "insufficient",  # Y-010 has no fitment at all
    "X-009": "incomplete",
    "X-010": "incomplete",
    "Y-006": "incomplete",
    "Y-010": "incomplete",
    "Y-011": "incomplete",
}


def test_every_trap_pattern_lands_in_its_category(archive):
    assert {key: item.category for key, item in open_items().items()} == EXPECTED


@pytest.mark.parametrize("pair", [
    "X-003~X-004",  # same size and fitment, different part type, no shared number
    "X-001~X-006",  # both carry OE numbers and they differ
    "X-002~Y-005",  # left and right, nothing shared
    "X-002~X-008",
])
def test_no_item_for_pairs_that_are_plainly_different(archive, pair):
    assert pair not in open_items()


def test_short_supplier_codes_never_trigger_anything(archive):
    triggers = [t for item in ReviewItem.objects.all() for t in item.triggers]

    assert not any("X-01-00" in t or "Y01X" in t for t in triggers)


def test_a_conflict_shows_both_values_and_where_each_came_from(archive):
    item = open_items()["X-006~Y-003"]

    part_type = next(c for c in item.conflicts if c["field"] == "part_type")
    assert (part_type["a"]["value"], part_type["b"]["value"]) == ("Front Grille", "Bug Screen")
    assert part_type["a"]["sources"][0]["cell"] == "C7"  # X-006 is spreadsheet row 7
    assert part_type["b"]["sources"][0]["column"] == "English Name"
    dims = next(c for c in item.conflicts if c["field"] == "dims")
    assert (dims["a"]["value"], dims["b"]["value"]) == ("122×75×7 cm", "120×75×8 cm")
    assert item.triggers == ["共享编号：OE-SHR-0001"] and "一号多品" in item.suggested_action


def test_missing_fields_say_which_side_lacks_them(archive):
    item = open_items()["X-011~Y-010"]

    assert {(m["field"], m["side"]) for m in item.missing} >= {("fitment", "b")}
    assert "一方没有适配" in item.triggers[0]


def test_agreements_are_listed_for_strong_pairs(archive):
    item = open_items()["X-002~Y-002"]

    assert {a["field"] for a in item.agreements} == {
        "part_type", "position", "fitment", "years", "dims"}
    assert item.conflicts == [] and item.missing == [] and item.strength == "strong"


def test_matching_never_merges(archive):
    records = SourceRecord.objects.count()

    matching.rematch()

    assert Product.objects.count() == records == Membership.objects.count() == 22
    assert set(Product.objects.values_list("status", flat=True)) == {"unreviewed"}
    assert Membership.objects.values("product").distinct().count() == records


def test_rematch_is_idempotent_and_keeps_item_ids(archive):
    before = {k: (i.pk, i.evidence_hash) for k, i in open_items().items()}

    counts = matching.rematch()

    assert {k: (i.pk, i.evidence_hash) for k, i in open_items().items()} == before
    assert counts["removed"] == 0


def test_a_decision_holds_until_the_evidence_changes(archive, monkeypatch):
    item = open_items()["X-001~Y-008"]
    ReviewItem.objects.filter(pk=item.pk).update(status="different")  # as M26 will record

    matching.rematch()
    assert "X-001~Y-008" not in open_items()

    real = matching._hash

    def changed_for_this_pair(category, *records):  # as if a new version changed a key field
        digest = real(category, *records)
        if {r.record_key for r in records} == {"X-001", "Y-008"}:
            digest = hashlib.sha256(digest.encode()).hexdigest()
        return digest

    monkeypatch.setattr(matching, "_hash", changed_for_this_pair)
    matching.rematch()

    reopened = open_items()["X-001~Y-008"]
    assert reopened.triggers[0] == "证据已变化（上次决定：判为不同）"
    assert ReviewItem.objects.get(pk=item.pk).status == "superseded"


def test_the_evidence_hash_does_not_depend_on_pair_order(archive):
    a = SourceRecord.objects.get(record_key="X-001")
    b = SourceRecord.objects.get(record_key="Y-001")

    assert matching.judge(a, b).evidence_hash == matching.judge(b, a).evidence_hash


def test_items_record_the_rules_version(archive):
    versions = set(ReviewItem.objects.values_list("rules_version", flat=True))

    assert versions == {matching.rules()["version"]}


def test_a_failure_in_matching_rolls_back_the_whole_ingest(user, monkeypatch):
    from apps.sources.tests.dataset import ingest_both

    def broken():
        raise RuntimeError("matching crashed")

    monkeypatch.setattr(matching, "rematch", broken)
    with pytest.raises(RuntimeError):
        ingest_both(user)

    assert not SourceRecord.objects.exists() and not Product.objects.exists()


def test_rematch_command(archive, capsys):
    call_command("archive_rematch")

    out = capsys.readouterr().out
    assert "规则版本" in out and "强证据疑似同一产品：2" in out
