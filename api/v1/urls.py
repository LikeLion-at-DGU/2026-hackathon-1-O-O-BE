from django.urls import include, path

urlpatterns = [
    path("admin/", include("apps.dashboard.urls")),
]
