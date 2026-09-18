"""Small presentation helpers for catalog templates."""

from django import template
from django.utils.html import format_html

register = template.Library()

_MATCH = {
    "exact": ("精确", "bg-emerald-100 text-emerald-800"),
    "normalized": ("归一化", "bg-blue-100 text-blue-800"),
    "prefix": ("前缀 / 包含", "bg-amber-100 text-amber-800"),
    "fuzzy": ("模糊", "bg-orange-100 text-orange-800"),
    "name": ("名称", "bg-slate-200 text-slate-700"),
}


@register.simple_tag
def match_badge(match_type: str):
    label, classes = _MATCH.get(match_type, (match_type, "bg-slate-200 text-slate-700"))
    return format_html(
        '<span class="inline-block rounded px-2 py-0.5 text-xs font-medium {}">{}</span>',
        classes,
        label,
    )


@register.simple_tag
def score_badge(score: int):
    classes = (
        "bg-red-100 text-red-800" if score < 40
        else "bg-amber-100 text-amber-800" if score < 70
        else "bg-emerald-100 text-emerald-800"
    )
    return format_html(
        '<span class="inline-block rounded px-2 py-0.5 text-xs font-medium {}">完整度 {}</span>',
        classes,
        score,
    )


@register.filter
def primary_image(part):
    """First image from the prefetched, primary-first list; no extra query."""
    images = list(part.images.all())
    return images[0] if images else None


@register.filter
def numbers_of_kind(part, kind):
    return [n for n in part.numbers.all() if n.kind == kind]
