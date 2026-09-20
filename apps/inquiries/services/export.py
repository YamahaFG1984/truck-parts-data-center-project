"""Listing exports for Alibaba and Shopify (PRD F8, docs/architecture.html §7.6).

Only reviewed products with a main image go out: a platform listing is public and
permanent, so half-finished data must not leak into it. Nothing supplier-facing
(cost, supplier name, supplier part number) is ever written to these files — the
price column is the suggested selling price, not the cost.

Each platform is a constant list of (column header, value key) pairs. Adapting a
template means editing that list; the row builder stays the same.
"""

import csv
import datetime as dt
from decimal import Decimal
from io import StringIO

from django.utils.html import escape
from django.utils.text import slugify

from apps.catalog.models import Part
from apps.suppliers.services.quoting import best_offer, suggested_price

COMPANY = "Demo Truck Parts Co., Ltd."
ORIGIN = "China"
EXPORTABLE_STATUSES = (Part.Status.REVIEWED, Part.Status.PUBLISHED)

ALIBABA_COLUMNS = [
    ("Product Name", "title"),
    ("Product SKU", "sku"),
    ("Category", "category"),
    ("Model Number", "model_number"),
    ("OE Number", "oe_numbers"),
    ("Cross Reference", "cross_numbers"),
    ("Applicable Vehicle", "fitments"),
    ("Specification", "specs"),
    ("Keywords", "keywords"),
    ("Product Description", "description"),
    ("Selling Points", "selling_points"),
    ("Place of Origin", "origin"),
    ("Unit Type", "unit"),
    ("Minimum Order Quantity", "moq"),
    ("FOB Price (USD)", "price"),
    ("Lead Time (days)", "lead_days"),
    ("Packaging Details", "packing"),
    ("Main Image URL", "image_url"),
]

SHOPIFY_COLUMNS = [
    ("Handle", "handle"),
    ("Title", "title"),
    ("Body (HTML)", "body_html"),
    ("Vendor", "vendor"),
    ("Type", "category"),
    ("Tags", "tags"),
    ("Published", "published"),
    ("Option1 Name", "option1_name"),
    ("Option1 Value", "option1_value"),
    ("Variant SKU", "sku"),
    ("Variant Grams", "grams"),
    ("Variant Inventory Policy", "inventory_policy"),
    ("Variant Fulfillment Service", "fulfillment"),
    ("Variant Price", "price"),
    ("Variant Requires Shipping", "requires_shipping"),
    ("Variant Taxable", "taxable"),
    ("Image Src", "image_url"),
    ("Image Position", "image_position"),
    ("Image Alt Text", "title"),
    ("SEO Title", "title"),
    ("SEO Description", "seo_description"),
    ("Status", "shopify_status"),
]

SEO_DESCRIPTION_MAX = 320


def eligible(parts) -> tuple[list[Part], list[tuple[str, str]]]:
    """Split parts into (exportable, [(sku, reason)]).

    Reads is_primary from the prefetched images, so a prefetched queryset costs
    no extra query per part.
    """
    exportable, excluded = [], []
    for part in parts:
        reasons = []
        if part.status not in EXPORTABLE_STATUSES:
            reasons.append(f"未审核（{part.get_status_display()}）")
        if not any(image.is_primary for image in part.images.all()):
            reasons.append("缺主图")
        if reasons:
            excluded.append((part.sku, "、".join(reasons)))
        else:
            exportable.append(part)
    return exportable, excluded


def to_alibaba_csv(parts, base_url: str = "") -> bytes:
    return _csv(ALIBABA_COLUMNS, parts, base_url)


def to_shopify_csv(parts, base_url: str = "") -> bytes:
    return _csv(SHOPIFY_COLUMNS, parts, base_url)


PLATFORMS = {
    "alibaba": ("Alibaba", to_alibaba_csv),
    "shopify": ("Shopify", to_shopify_csv),
}


def filename(platform: str) -> str:
    return f"{platform}-listing-{dt.date.today():%Y%m%d}.csv"


def _csv(columns, parts, base_url: str) -> bytes:
    """utf-8-sig so Excel shows Chinese and the euro-style headers correctly;
    csv.writer quotes the newlines and commas inside descriptions."""
    buffer = StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow([header for header, _ in columns])
    for part in parts:
        values = _values(part, base_url)
        writer.writerow([values[key] for _, key in columns])
    return buffer.getvalue().encode("utf-8-sig")


def _values(part: Part, base_url: str) -> dict:
    numbers = list(part.numbers.all())
    oe = [n.number for n in numbers if n.kind == "OE"]
    cross = [f"{n.brand.name} {n.number}" if n.brand else n.number
             for n in numbers if n.kind == "CROSS"]
    offer = best_offer(part)
    price = suggested_price(offer.unit_cost_usd) if offer else None
    title = part.title_en or part.name_en or part.sku
    fitments = "; ".join(str(f) for f in part.fitments.all())
    specs = "; ".join(f"{key}: {value}" for key, value in part.attributes.items())
    description = part.description_en
    packaging = part.packaging or {}
    return {
        "sku": part.sku,
        "title": title,
        "category": part.category.name_en or part.category.name if part.category_id else "",
        "model_number": oe[0] if oe else part.sku,
        "oe_numbers": "; ".join(oe),
        "cross_numbers": "; ".join(cross),
        "fitments": fitments,
        "specs": specs,
        "keywords": ", ".join(part.keywords),
        "description": description,
        "selling_points": "\n".join(f"- {point}" for point in part.selling_points),
        "origin": ORIGIN,
        "unit": packaging.get("unit") or "piece",
        "moq": offer.moq if offer and offer.moq else "",
        "price": price if price is not None else "",
        "lead_days": offer.lead_days if offer and offer.lead_days else "",
        "packing": _packing(packaging),
        "image_url": _image_url(part, base_url),
        # Shopify-only
        "handle": slugify(part.sku),
        "body_html": _body_html(part, title, fitments, specs, oe, cross),
        "vendor": COMPANY,
        "tags": ", ".join([*part.keywords, *oe]),
        "published": "TRUE",
        "option1_name": "Title",
        "option1_value": "Default Title",
        "grams": _grams(packaging),
        "inventory_policy": "continue",
        "fulfillment": "manual",
        "requires_shipping": "TRUE",
        "taxable": "TRUE",
        "image_position": 1,
        "seo_description": (description or title)[:SEO_DESCRIPTION_MAX],
        "shopify_status": "active" if part.status == Part.Status.PUBLISHED else "draft",
    }


def _packing(packaging: dict) -> str:
    """One line, unlike the quotation's wrapped cell: a CSV field reads better flat."""
    parts = []
    if packaging.get("pcs_per_carton"):
        parts.append(f"{packaging['pcs_per_carton']} {packaging.get('unit', 'pc')}/carton")
    if packaging.get("carton_l_cm"):
        parts.append(f"{packaging['carton_l_cm']}x{packaging.get('carton_w_cm')}x"
                     f"{packaging.get('carton_h_cm')} cm")
    if packaging.get("gross_weight_kg"):
        parts.append(f"G.W. {packaging['gross_weight_kg']} kg")
    return "; ".join(parts)


def _grams(packaging: dict) -> int | str:
    weight = packaging.get("gross_weight_kg")
    return int(Decimal(str(weight)) * 1000) if weight else ""


def _image_url(part: Part, base_url: str) -> str:
    image = next((i for i in part.images.all() if i.is_primary), None)
    if image is None:
        return ""
    return f"{base_url.rstrip('/')}{image.image.url}" if base_url else image.image.url


def _body_html(part: Part, title: str, fitments: str, specs: str, oe, cross) -> str:
    """Shopify's description column is HTML; everything user-supplied is escaped."""
    blocks = [f"<p>{escape(part.description_en or title)}</p>"]
    if part.selling_points:
        blocks.append("<ul>" + "".join(f"<li>{escape(p)}</li>" for p in part.selling_points)
                      + "</ul>")
    rows = [("OE No.", "; ".join(oe)), ("Cross Ref.", "; ".join(cross)),
            ("Application", fitments), ("Specification", specs)]
    rows = [(label, value) for label, value in rows if value]
    if rows:
        blocks.append("<table>" + "".join(
            f"<tr><td>{label}</td><td>{escape(value)}</td></tr>" for label, value in rows
        ) + "</table>")
    for question in part.faq:
        blocks.append(f"<p><strong>{escape(question.get('q', ''))}</strong><br>"
                      f"{escape(question.get('a', ''))}</p>")
    return "".join(blocks)
