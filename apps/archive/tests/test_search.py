"""Archive search (docs/archive-design.html §11): number, keyword, brand, supplier."""

import pytest

from apps.archive.models import Membership
from apps.archive.services import review
from apps.archive.services.search import search
from apps.suppliers.models import Supplier

from .conftest import find_item

pytestmark = pytest.mark.django_db


def keys(results):
    return {h.record.record_key for r in results for h in r.hits}


def test_a_number_matches_however_it_is_written(archive):
    results = search("oe tst 1001")
    assert keys(results) == {"X-001", "Y-001"}
    assert all(r.by_number for r in results)
    assert {h.label for r in results for h in r.hits} == {"OE / 互换号"}


def test_numbers_hit_supplier_skus_and_record_ids(archive):
    assert keys(search("Y02L")) == {"Y-002"}
    assert keys(search("x-011")) == {"X-011"}


def test_a_short_partial_number_matches_nothing(archive):
    """"01" appears inside X-01-00 and Y01X; partial numbers need five characters."""
    assert not [r for r in search("01") if r.by_number]


def test_a_partial_number_of_five_characters_matches(archive):
    assert {"X-001", "Y-001"} <= keys(search("TST100"))


def test_a_keyword_matches_names_and_types(archive):
    results = search("fan shroud")
    assert keys(results) == {"X-004", "X-010"}
    assert {h.label for r in results for h in r.hits} == {"原始名称", "品类"}


def test_brand_and_supplier(archive):
    assert "X-003" in keys(search("freightliner"))
    results = search("Supplier Y")
    assert keys(results) == {f"Y-{n:03d}" for n in range(1, 12)}


def test_results_are_grouped_by_product(archive, user):
    review.confirm_same(find_item("X-001~Y-001"), user, "同一件")
    results = search("OE-TST-1001")
    assert len(results) == 1
    assert results[0].product == Membership.objects.get(record_key="X-001").product
    assert len(results[0].hits) == 2


def test_narrowing_to_one_supplier(archive):
    y = Supplier.objects.get(name="Supplier Y")
    assert keys(search("OE-TST-1001", y)) == {"Y-001"}


def test_an_empty_query_returns_nothing(archive):
    assert search("  ") == []
