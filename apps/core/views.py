from django.views.generic import TemplateView


class HomeView(TemplateView):
    """Placeholder home page; the real dashboard arrives in M20."""

    template_name = "core/home.html"
