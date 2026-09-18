from django.urls import path

from . import views

app_name = "ai"

urlpatterns = [
    path("ai/review/", views.ReviewQueueView.as_view(), name="review_queue"),
    path("ai/enrich/<str:sku>/", views.EnrichView.as_view(), name="enrich"),
    path("ai/suggestions/<int:pk>/accept/", views.AcceptView.as_view(), name="accept"),
    path("ai/suggestions/<int:pk>/reject/", views.RejectView.as_view(), name="reject"),
]
