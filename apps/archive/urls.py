from django.urls import path

from . import views

app_name = "archive"

urlpatterns = [
    path("archive/", views.SearchView.as_view(), name="search"),
    path("archive/products/<int:pk>/", views.ProductView.as_view(), name="product"),
    path("archive/records/<int:pk>/", views.RecordView.as_view(), name="record"),
    path("archive/export/<str:kind>/", views.ExportView.as_view(), name="export"),
    path("archive/review/", views.QueueView.as_view(), name="queue"),
    path("archive/review/bulk/", views.BulkConfirmView.as_view(), name="bulk_confirm"),
    path("archive/review/<int:pk>/", views.ItemView.as_view(), name="item"),
    path("archive/memberships/<int:pk>/detach/", views.DetachView.as_view(), name="detach"),
]
