from django.urls import path

from apps.dashboard.views import AdminAuthView

urlpatterns = [
    path("auth", AdminAuthView.as_view(), name="admin-auth"),
]
