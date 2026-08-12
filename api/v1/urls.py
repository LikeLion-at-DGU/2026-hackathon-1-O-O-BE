from django.urls import include, path

urlpatterns = [
    path("", include("apps.visits.urls")),
    path("admin/", include("apps.dashboard.urls")),
]
