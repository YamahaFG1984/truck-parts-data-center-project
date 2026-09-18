from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.catalog.models import Part, PartImage, PartNumber

from .factories import (
    BRAKE_PAD_SCHEMA,
    BrandFactory,
    CategoryFactory,
    FitmentFactory,
    PartFactory,
    PartImageFactory,
    PartNumberFactory,
)

pytestmark = pytest.mark.django_db


def _integrity_error(fn):
    with pytest.raises(IntegrityError), transaction.atomic():
        fn()


# --- PartNumber -----------------------------------------------------------------


def test_save_normalizes_number():
    pn = PartNumberFactory(number="  2044-3906 ")

    assert pn.number == "2044-3906"
    assert pn.number_norm == "20443906"


def test_bulk_create_also_normalizes():
    part = PartFactory()
    PartNumber.objects.bulk_create([PartNumber(part=part, number="A 000 420 15 20", kind="OE")])

    assert PartNumber.objects.get(part=part).number_norm == "A0004201520"


def test_same_number_twice_on_one_part_is_rejected():
    first = PartNumberFactory(number="20443906")

    _integrity_error(
        lambda: PartNumberFactory(
            part=first.part, number="2044-3906", kind=first.kind, brand=first.brand
        )
    )


def test_same_number_without_brand_twice_on_one_part_is_rejected():
    first = PartNumberFactory(number="20443906", brand=None)

    _integrity_error(
        lambda: PartNumberFactory(part=first.part, number="20443906", kind=first.kind, brand=None)
    )


def test_same_number_on_two_parts_is_allowed_as_alternatives():
    brand = BrandFactory(name="Volvo")
    PartNumberFactory(number="20443906", brand=brand)
    PartNumberFactory(number="2044 3906", brand=brand)

    assert PartNumber.objects.filter(number_norm="20443906").values("part").distinct().count() == 2


def test_same_number_as_oe_and_cross_on_one_part_is_allowed():
    first = PartNumberFactory(number="20443906", kind="OE")
    PartNumberFactory(part=first.part, number="20443906", kind="CROSS", brand=first.brand)

    assert first.part.numbers.count() == 2


def test_number_without_letters_or_digits_is_invalid():
    pn = PartNumber(part=PartFactory(), number="--- / ---", kind="OE")

    with pytest.raises(ValidationError):
        pn.full_clean()
    _integrity_error(pn.save)


def test_confidence_range_constraint_is_inherited():
    _integrity_error(lambda: PartNumberFactory(confidence=Decimal("1.50")))


def test_of_kind():
    part = PartFactory()
    PartNumberFactory(part=part, kind="OE")
    PartNumberFactory(part=part, kind="CROSS")

    assert list(part.numbers.of_kind("CROSS").values_list("kind", flat=True)) == ["CROSS"]


# --- Part ------------------------------------------------------------------------


def test_part_defaults():
    part = Part.objects.create(sku="FIT-TST-99999")

    assert part.status == Part.Status.DRAFT
    assert part.attributes == {} and part.packaging == {} and part.keywords == []
    assert part.completeness_score == 0
    assert part.source == "manual" and part.confidence == Decimal("1.00")


def test_packaging_validation_rejects_bad_values():
    part = PartFactory.build(packaging={"pcs_per_carton": -1, "unit": "box"})

    with pytest.raises(ValidationError) as exc:
        part.full_clean()
    assert "packaging" in exc.value.message_dict


def test_packaging_validation_rejects_unknown_keys():
    part = PartFactory.build(packaging={"colour": "red"})

    with pytest.raises(ValidationError):
        part.full_clean()


def test_valid_packaging_passes():
    part = PartFactory(packaging={"unit": "set", "pcs_per_carton": 20, "gross_weight_kg": 12.5})

    part.full_clean()


def test_attributes_checked_against_category_schema():
    category = CategoryFactory(attribute_schema=BRAKE_PAD_SCHEMA)
    part = PartFactory.build(
        category=category,
        attributes={"length_mm": "210mm", "friction_material": "steel", "colour": "red"},
    )

    with pytest.raises(ValidationError) as exc:
        part.full_clean()
    assert len(exc.value.message_dict["attributes"]) == 3


def test_missing_required_attribute_is_allowed():
    category = CategoryFactory(attribute_schema=BRAKE_PAD_SCHEMA)
    part = PartFactory(category=category, attributes={"length_mm": 210})

    part.full_clean()  # incompleteness is scored, not rejected


def test_category_rejects_enum_without_options():
    category = CategoryFactory.build(
        attribute_schema={"fields": [{"key": "side", "label": "左右", "type": "enum"}]}
    )

    with pytest.raises(ValidationError):
        category.full_clean()


def test_completeness_score_cannot_exceed_100():
    _integrity_error(lambda: PartFactory(completeness_score=101))


# --- Fitment ---------------------------------------------------------------------


def test_duplicate_fitment_with_empty_years_is_rejected():
    first = FitmentFactory(year_from=None, year_to=None, engine="")

    _integrity_error(
        lambda: FitmentFactory(
            part=first.part, make="VOLVO", model="fh12", engine="", year_from=None, year_to=None
        )
    )


def test_fitment_year_order():
    _integrity_error(lambda: FitmentFactory(year_from=2005, year_to=1993))


# --- PartImage -------------------------------------------------------------------


def test_first_image_becomes_primary_and_path_uses_sku():
    image = PartImageFactory(part=PartFactory(sku="FIT-BRK-00123"))

    assert image.is_primary
    assert image.image.name.startswith("parts/FIT-BRK-00123/")
    assert "photo" not in image.image.name  # uploaded file name is discarded


def test_new_primary_demotes_old_one():
    part = PartFactory()
    first = PartImageFactory(part=part)
    second = PartImageFactory(part=part)
    assert not second.is_primary

    second.is_primary = True
    second.save()

    first.refresh_from_db()
    assert not first.is_primary
    assert part.images.filter(is_primary=True).count() == 1


def test_database_blocks_two_primaries():
    part = PartFactory()
    PartImageFactory(part=part)
    second = PartImageFactory(part=part)

    _integrity_error(lambda: PartImage.objects.filter(pk=second.pk).update(is_primary=True))


# --- QuerySets -------------------------------------------------------------------


def test_missing_filters():
    complete = PartFactory()
    PartNumberFactory(part=complete, kind="OE")
    PartImageFactory(part=complete)
    bare = PartFactory(category=None)

    assert set(Part.objects.missing("oe")) == {bare}
    assert set(Part.objects.missing("image")) == {bare}
    assert set(Part.objects.missing("category")) == {bare}
    assert set(Part.objects.missing("fitment")) == {complete, bare}


def test_missing_rejects_unknown_item():
    with pytest.raises(ValueError):
        Part.objects.missing("colour")


def test_reviewed_includes_published():
    PartFactory(status="draft")
    reviewed = PartFactory(status="reviewed")
    published = PartFactory(status="published")

    assert set(Part.objects.reviewed()) == {reviewed, published}
    assert set(Part.objects.published()) == {published}


def test_with_related_uses_fixed_query_count(django_assert_num_queries):
    for _ in range(3):
        part = PartFactory()
        PartNumberFactory(part=part)
        FitmentFactory(part=part)
        PartImageFactory(part=part)

    with django_assert_num_queries(4):  # parts+category, numbers+brand, fitments, images
        for part in Part.objects.with_related():
            [n.brand for n in part.numbers.all()]
            list(part.fitments.all())
            list(part.images.all())
