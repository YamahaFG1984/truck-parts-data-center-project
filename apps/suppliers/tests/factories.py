import datetime as dt
from decimal import Decimal

import factory
from factory.django import DjangoModelFactory

from apps.catalog.tests.factories import PartFactory
from apps.suppliers.models import Supplier, SupplierOffer


class SupplierFactory(DjangoModelFactory):
    class Meta:
        model = Supplier

    name = factory.Sequence(lambda n: f"Demo Supplier {n}")
    rating = 3


class SupplierOfferFactory(DjangoModelFactory):
    class Meta:
        model = SupplierOffer

    supplier = factory.SubFactory(SupplierFactory)
    part = factory.SubFactory(PartFactory)
    supplier_pn = factory.Sequence(lambda n: f"HB-{n:04d}")
    unit_cost_usd = Decimal("18.50")
    moq = 50
    lead_days = 25
    quoted_at = dt.date(2026, 9, 1)
