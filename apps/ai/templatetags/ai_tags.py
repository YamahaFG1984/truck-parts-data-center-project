from django import template
from django.utils.html import format_html, format_html_join
from django.utils.safestring import mark_safe

register = template.Library()


@register.filter
def show_value(value):
    """Readable HTML for a suggestion value: text, list, FAQ list or spec dict."""
    if value in (None, "", [], {}):
        return mark_safe('<span class="text-slate-400">（空）</span>')
    if isinstance(value, dict):
        return format_html_join("", "<div><span class='text-slate-500'>{}</span>: {}</div>",
                                value.items())
    if isinstance(value, list) and value and isinstance(value[0], dict):  # FAQ
        return format_html_join(
            "", "<div class='mb-1'><div class='font-medium'>Q: {}</div><div>A: {}</div></div>",
            ((item.get("q", ""), item.get("a", "")) for item in value),
        )
    if isinstance(value, list):
        return format_html("<ul class='list-disc pl-4'>{}</ul>",
                           format_html_join("", "<li>{}</li>", ((v,) for v in value)))
    return format_html("<div class='whitespace-pre-line'>{}</div>", value)
