from django.urls import path

from . import views

app_name = "catalog"

urlpatterns = [
    path("search/", views.SearchView.as_view(), name="search"),
    path("parts/<str:sku>/", views.PartDetailView.as_view(), name="part_detail"),
]
