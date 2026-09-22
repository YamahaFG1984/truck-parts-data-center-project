from django.urls import path

from . import views

app_name = "archive"

urlpatterns = [
    path("archive/review/", views.QueueView.as_view(), name="queue"),
    path("archive/review/bulk/", views.BulkConfirmView.as_view(), name="bulk_confirm"),
    path("archive/review/<int:pk>/", views.ItemView.as_view(), name="item"),
    path("archive/memberships/<int:pk>/detach/", views.DetachView.as_view(), name="detach"),
]
