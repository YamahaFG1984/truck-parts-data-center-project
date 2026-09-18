from django.urls import path

from . import views

app_name = "catalog"

urlpatterns = [
    path("search/", views.SearchView.as_view(), name="search"),
    path("parts/", views.PartListView.as_view(), name="part_list"),
    path("parts/<str:sku>/", views.PartDetailView.as_view(), name="part_detail"),
]
