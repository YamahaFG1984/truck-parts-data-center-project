from django.urls import path

from . import views

app_name = "sources"

urlpatterns = [
    path("sources/", views.FileListView.as_view(), name="list"),
    path("sources/<int:pk>/", views.FileDetailView.as_view(), name="detail"),
    path("sources/<int:pk>/mapping/", views.MappingView.as_view(), name="mapping"),
    path("sources/<int:pk>/preview/", views.PreviewView.as_view(), name="preview"),
    path("sources/<int:pk>/original/", views.OriginalView.as_view(), name="original"),
]
