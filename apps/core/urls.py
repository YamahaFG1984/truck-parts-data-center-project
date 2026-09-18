from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.HomeView.as_view(), name="home"),
    path("quality/", views.QualityDashboardView.as_view(), name="quality"),
    path("jobs/<int:pk>/", views.JobView.as_view(), name="job"),
]
