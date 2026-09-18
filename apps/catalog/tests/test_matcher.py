import pytest

from apps.catalog.services import matcher
from apps.catalog.services.matcher import Candidate, alternatives, search

from .factories import BrandFactory, CategoryFactory, FitmentFactory, PartFactory, PartNumberFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def pad():
    """Volvo brake pad with an OE and a cross number."""
    part = PartFactory(sku="FIT-BPD-00001", name_en="Brake Pad Set, Front Axle",
                       completeness_score=80)
    PartNumberFactory(part=part, number="20443906", kind="OE", brand=BrandFactory(name="Volvo"))
    PartNumberFactory(part=part, number="K001234", kind="CROSS",
                      brand=BrandFactory(name="Knorr-Bremse"))
    FitmentFactory(part=part, make="Volvo", model="FH12")
    return part


def _skus(results):
    return [c.part.sku for c in results]


# --- empty / junk ---------------------------------------------------------------------


@pytest.mark.parametrize("raw", ["", "   ", None, "--- / ---", "oe:"])
def test_empty_or_symbol_input_returns_nothing(raw, pad):
    assert search(raw) == []


# --- L1 exact / normalized ----------------------------------------------------------------


def test_exact_number(pad):
    [hit] = search("20443906")

    assert hit.part == pad
    assert (hit.match_type, hit.score) == ("exact", 1.0)
    assert (hit.matched_number, hit.matched_kind) == ("20443906", "OE")


@pytest.mark.parametrize("raw", ["2044-3906", "20 443 906", "２０４４３９０６", "oe:2044 3906"])
def test_dirty_formats_match_as_normalized(raw, pad):
    [hit] = search(raw)

    assert hit.part == pad
    assert hit.match_type == "normalized"


def test_cross_number_finds_part(pad):
    [hit] = search("k001234")

    assert hit.part == pad and hit.matched_kind == "CROSS"


def test_unique_exact_hit_skips_lower_levels(pad, django_assert_num_queries):
    PartNumberFactory(number="204439061")  # would match at L2 if L2 ran

    with django_assert_num_queries(1):
        results = search("20443906")

    assert _skus(results) == [pad.sku]


def test_shared_oe_returns_every_part_then_fills_lower_levels(pad):
    twin = PartFactory(completeness_score=40)
    PartNumberFactory(part=twin, number="2044 3906", kind="OE")
    variant = PartFactory()
    PartNumberFactory(part=variant, number="20443906-1")

    results = search("20443906")

    assert _skus(results)[:2] == [pad.sku, twin.sku]  # exact first, then normalized
    assert results[2].part == variant and results[2].match_type == "prefix"


# --- L2 prefix / contains --------------------------------------------------------------------


@pytest.mark.parametrize("raw", ["20443906-1", "20443906/2", "volvo 20443906", "2044390"])
def test_prefix_and_suffix_variants(raw, pad):
    results = search(raw)

    assert results and results[0].part == pad
    assert results[0].match_type == "prefix"


def test_prefix_ignores_very_short_contained_numbers():
    tiny = PartFactory()
    PartNumberFactory(part=tiny, number="1234", brand=None)

    assert tiny not in [c.part for c in search("99912349")]


# --- L3 fuzzy --------------------------------------------------------------------------------


@pytest.mark.postgres
@pytest.mark.parametrize(
    ("raw", "label"),
    [("2O443906", "letter O for zero"), ("20443960", "swapped digits"),
     ("20443916", "one wrong digit")],
)
def test_fuzzy_trigram(raw, label, pad):
    results = search(raw)

    assert results, label
    assert results[0].part == pad
    assert results[0].match_type == "fuzzy"
    assert matcher.FUZZY_THRESHOLD <= results[0].score < 0.95


@pytest.mark.postgres
def test_fuzzy_trigram_rejects_unrelated_numbers(pad):
    assert search("31024701") == []


@pytest.mark.parametrize("raw", ["2O443906", "20443960", "20443916"])
def test_fuzzy_python_fallback(raw, pad):
    [hit] = matcher._fuzzy_python(raw, limit=5)

    assert hit.part == pad
    assert hit.score >= matcher.FALLBACK_THRESHOLD


def test_fuzzy_python_fallback_rejects_unrelated(pad):
    assert matcher._fuzzy_python("31024701", limit=5) == []


# --- SKU and text ----------------------------------------------------------------------------


def test_sku_exact_and_prefix(pad):
    PartFactory(sku="FIT-BPD-00002")

    [hit] = search("fit-bpd-00001")
    assert hit.part == pad and hit.match_type == "exact" and hit.matched_kind == "SKU"

    assert _skus(search("sku:FIT-BPD")) == ["FIT-BPD-00001", "FIT-BPD-00002"]


def test_name_and_vehicle_tokens(pad):
    other = PartFactory(name_en="Brake Pad Set, Rear Axle")
    FitmentFactory(part=other, make="Scania", model="R-series")

    assert _skus(search("brake pad volvo")) == [pad.sku]
    assert _skus(search("brake pad FH12")) == [pad.sku]
    assert set(_skus(search("brake pad"))) == {pad.sku, other.sku}


def test_name_search_expands_brand_aliases(pad):
    assert _skus(search("沃尔沃 brake")) == [pad.sku]


def test_name_search_matches_chinese_names_and_category():
    category = CategoryFactory(name="刹车片")
    part = PartFactory(name_zh="前刹车片", category=category)

    assert _skus(search("刹车片")) == [part.sku]


@pytest.mark.postgres
def test_misspelled_name_falls_back_to_trigram(pad):
    results = search("brak pads")

    assert results and results[0].part == pad


# --- ranking, limit, alternatives ------------------------------------------------------------


def test_one_candidate_per_part_keeps_best_match(pad):
    PartNumberFactory(part=pad, number="20443906", kind="CROSS", brand=None)

    results = search("2044-3906")

    assert len(results) == 1


def test_results_are_limited_and_stably_ordered():
    for i in range(30):
        part = PartFactory(sku=f"FIT-LIM-{i:05d}", completeness_score=i)
        PartNumberFactory(part=part, number=f"55550{i:03d}")

    first = search("55550", limit=10)
    second = search("55550", limit=10)

    assert len(first) == 10
    assert _skus(first) == _skus(second)
    scores = [c.part.completeness_score for c in first]
    assert scores == sorted(scores, reverse=True)  # same match level: fuller data first


def test_default_limit_is_module_constant():
    for i in range(matcher.MAX_RESULTS + 5):
        PartNumberFactory(number=f"77770{i:03d}")

    assert len(search("77770")) == matcher.MAX_RESULTS


def test_alternatives_share_oe_or_cross_and_exclude_self(pad, django_assert_num_queries):
    via_oe = PartFactory()
    PartNumberFactory(part=via_oe, number="2044-3906", kind="OE")
    via_cross = PartFactory()
    PartNumberFactory(part=via_cross, number="K 001234", kind="CROSS")
    supplier_only = PartFactory()
    PartNumberFactory(part=supplier_only, number="20443906", kind="SUPPLIER")
    PartNumberFactory(part=pad, number="HB-2044", kind="SUPPLIER")

    with django_assert_num_queries(1):
        found = set(alternatives(pad))

    assert found == {via_oe, via_cross}


def test_candidate_sort_key_prefers_better_match_then_fuller_data():
    a = PartFactory.build(sku="A", completeness_score=10)
    b = PartFactory.build(sku="B", completeness_score=90)
    candidates = [
        Candidate(b, "fuzzy", 0.9),
        Candidate(a, "normalized", 0.95),
        Candidate(b, "normalized", 0.95),
    ]
    ranked = sorted(candidates, key=lambda c: c.sort_key)
    assert [(c.part.sku, c.match_type) for c in ranked] == [
        ("B", "normalized"), ("A", "normalized"), ("B", "fuzzy"),
    ]
