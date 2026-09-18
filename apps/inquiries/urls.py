from django.urls import path

from . import views

app_name = "inquiries"

urlpatterns = [
    path("inquiry/image/", views.ImageInquiryView.as_view(), name="image"),
    path("inquiry/<int:pk>/", views.InquiryDetailView.as_view(), name="detail"),
    path("inquiry/<int:pk>/retry/", views.RetryView.as_view(), name="retry"),
    path("inquiry/<int:pk>/confirm/", views.ConfirmView.as_view(), name="confirm"),
]
