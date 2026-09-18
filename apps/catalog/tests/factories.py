import factory
from factory.django import DjangoModelFactory

from apps.catalog.models import Brand, Category, Fitment, Part, PartImage, PartNumber

BRAKE_PAD_SCHEMA = {
    "fields": [
        {"key": "length_mm", "label": "长度", "type": "number", "unit": "mm", "required": True},
        {"key": "width_mm", "label": "宽度", "type": "number", "unit": "mm", "required": True},
        {
            "key": "friction_material",
            "label": "摩擦材料",
            "type": "enum",
            "options": ["semi-metallic", "ceramic", "organic"],
        },
    ]
}


class CategoryFactory(DjangoModelFactory):
    class Meta:
        model = Category

    name = factory.Sequence(lambda n: f"分类{n}")
    name_en = factory.Sequence(lambda n: f"Category {n}")
    code = "TST"
    attribute_schema = factory.LazyFunction(lambda: {"fields": []})


class BrandFactory(DjangoModelFactory):
    class Meta:
        model = Brand

    name = factory.Sequence(lambda n: f"Brand{n}")
    kind = Brand.Kind.OEM


class PartFactory(DjangoModelFactory):
    class Meta:
        model = Part

    sku = factory.Sequence(lambda n: f"FIT-TST-{n:05d}")
    name_en = "Brake Pad Set"
    category = factory.SubFactory(CategoryFactory)


class PartNumberFactory(DjangoModelFactory):
    class Meta:
        model = PartNumber

    part = factory.SubFactory(PartFactory)
    number = factory.Sequence(lambda n: f"2044-{n:04d}")
    kind = PartNumber.Kind.OE
    brand = factory.SubFactory(BrandFactory)


class FitmentFactory(DjangoModelFactory):
    class Meta:
        model = Fitment

    part = factory.SubFactory(PartFactory)
    make = "Volvo"
    model = "FH12"
    year_from = 1993
    year_to = 2005


class PartImageFactory(DjangoModelFactory):
    class Meta:
        model = PartImage

    part = factory.SubFactory(PartFactory)
    image = factory.django.ImageField(filename="photo.jpg", width=40, height=30)
