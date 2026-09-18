from django.urls import path

from . import views

app_name = "inquiries"

urlpatterns = [
    path("inquiry/", views.InquiryListView.as_view(), name="list"),
    path("inquiry/image/", views.ImageInquiryView.as_view(), name="image"),
    path("inquiry/<int:pk>/quote/", views.QuoteView.as_view(), name="quote"),
    path("inquiry/<int:pk>/quote.xlsx", views.QuoteDownloadView.as_view(), name="quote_xlsx"),
    path("inquiry/<int:pk>/", views.InquiryDetailView.as_view(), name="detail"),
    path("inquiry/<int:pk>/retry/", views.RetryView.as_view(), name="retry"),
    path("inquiry/<int:pk>/confirm/", views.ConfirmView.as_view(), name="confirm"),
]
