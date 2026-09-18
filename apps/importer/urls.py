from django.urls import path

from . import views

app_name = "importer"

urlpatterns = [
    path("import/", views.UploadView.as_view(), name="upload"),
    path("import/<int:pk>/", views.PreviewView.as_view(), name="preview"),
    path("import/<int:pk>/mapping/", views.MappingView.as_view(), name="mapping"),
]
