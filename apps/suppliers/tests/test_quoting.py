from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction
from django.template.loader import render_to_string
from django.test import RequestFactory
from django.urls import reverse

from apps.catalog.models import Part
from apps.catalog.tests.factories import PartFactory
from apps.suppliers.context_processors import cost_visibility
from apps.suppliers.services.quoting import best_offer, suggested_price

from .factories import SupplierFactory, SupplierOfferFactory

pytestmark = pytest.mark.django_db


def _integrity_error(fn):
    with pytest.raises(IntegrityError), transaction.atomic():
        fn()


# --- best_offer ----------------------------------------------------------------------


def test_best_offer_is_cheapest():
    part = PartFactory()
    SupplierOfferFactory(part=part, unit_cost_usd=Decimal("18.50"))
    cheap = SupplierOfferFactory(part=part, unit_cost_usd=Decimal("17.90"))

    assert best_offer(part) == cheap


def test_best_offer_equal_price_prefers_shorter_lead_time():
    part = PartFactory()
    SupplierOfferFactory(part=part, unit_cost_usd=Decimal("17.90"), lead_days=45)
    fast = SupplierOfferFactory(part=part, unit_cost_usd=Decimal("17.90"), lead_days=30)
    SupplierOfferFactory(part=part, unit_cost_usd=Decimal("17.90"), lead_days=None)

    assert best_offer(part) == fast


def test_best_offer_none_without_offers():
    assert best_offer(PartFactory()) is None


def test_best_offer_uses_prefetched_offers(django_assert_num_queries):
    part = PartFactory()
    SupplierOfferFactory.create_batch(3, part=part)
    part = Part.objects.prefetch_related("offers").get(pk=part.pk)

    with django_assert_num_queries(0):
        best_offer(part)


# --- suggested_price ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("cost", "margin", "expected"),
    [
        (Decimal("17.90"), Decimal("0.25"), Decimal("22.38")),  # 22.375 rounds half up
        (Decimal("10"), Decimal("0.25"), Decimal("12.50")),
        (Decimal("0.01"), Decimal("0.25"), Decimal("0.01")),  # 0.0125
        (Decimal("100.00"), Decimal("0"), Decimal("100.00")),
        (Decimal("19.99"), "0.3", Decimal("25.99")),  # 25.987
    ],
)
def test_suggested_price(cost, margin, expected):
    price = suggested_price(cost, margin)

    assert price == expected
    assert isinstance(price, Decimal) and price.as_tuple().exponent == -2


def test_suggested_price_uses_default_margin(settings):
    settings.DEFAULT_MARGIN = Decimal("0.40")

    assert suggested_price(Decimal("10")) == Decimal("14.00")


def test_suggested_price_none_without_cost():
    assert suggested_price(None) is None


# --- model constraints -------------------------------------------------------------------


def test_one_offer_per_supplier_part_and_day():
    offer = SupplierOfferFactory()

    _integrity_error(
        lambda: SupplierOfferFactory(
            supplier=offer.supplier, part=offer.part, quoted_at=offer.quoted_at
        )
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"unit_cost_usd": Decimal("0")},
        {"moq": 0},
        {"valid_until": "2026-08-01"},  # before quoted_at 2026-09-01
    ],
)
def test_offer_check_constraints(overrides):
    _integrity_error(lambda: SupplierOfferFactory(**overrides))


def test_supplier_rating_range():
    _integrity_error(lambda: SupplierFactory(rating=6))


# --- catalog integration -----------------------------------------------------------------


def test_with_min_cost_annotation():
    with_offers = PartFactory()
    SupplierOfferFactory(part=with_offers, unit_cost_usd=Decimal("30.00"))
    SupplierOfferFactory(part=with_offers, unit_cost_usd=Decimal("21.40"))
    without = PartFactory()

    costs = dict(Part.objects.with_min_cost().values_list("pk", "min_cost"))

    assert costs == {with_offers.pk: Decimal("21.40"), without.pk: None}


def test_missing_offer_filter():
    SupplierOfferFactory()
    bare = PartFactory()

    assert list(Part.objects.missing("offer")) == [bare]


# --- cost visibility ----------------------------------------------------------------------


def test_cost_visibility_flag(django_user_model):
    request = RequestFactory().get("/")
    request.user = django_user_model.objects.create_user("sales", password="x")
    assert cost_visibility(request) == {"can_view_cost": True}

    from django.contrib.auth.models import AnonymousUser

    request.user = AnonymousUser()
    assert cost_visibility(request) == {"can_view_cost": False}


@pytest.mark.parametrize("can_view_cost", [True, False])
def test_card_hides_cost_but_keeps_suggested_price(can_view_cost):
    part = PartFactory()
    SupplierOfferFactory(part=part, unit_cost_usd=Decimal("17.90"))
    part = Part.objects.with_related().get(pk=part.pk)

    html = render_to_string(
        "catalog/partials/part_card.html", {"part": part, "can_view_cost": can_view_cost}
    )

    assert "$22.38" in html
    assert ("$17.90" in html) is can_view_cost


def test_detail_page_lists_offers_cheapest_first(admin_client):
    part = PartFactory()
    SupplierOfferFactory(part=part, supplier=SupplierFactory(name="Slow Co"),
                         unit_cost_usd=Decimal("17.90"), lead_days=45)
    SupplierOfferFactory(part=part, supplier=SupplierFactory(name="Fast Co"),
                         unit_cost_usd=Decimal("17.90"), lead_days=20)

    body = admin_client.get(reverse("catalog:part_detail", args=[part.sku])).content.decode()

    assert body.index("Fast Co") < body.index("Slow Co")
    assert "$22.38" in body


@pytest.mark.parametrize("model", ["supplier", "supplieroffer"])
def test_admin_pages(admin_client, model):
    SupplierOfferFactory()

    assert admin_client.get(reverse(f"admin:suppliers_{model}_changelist")).status_code == 200
    assert admin_client.get(reverse(f"admin:suppliers_{model}_add")).status_code == 200
