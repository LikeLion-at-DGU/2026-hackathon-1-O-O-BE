from django.urls import path

from apps.dashboard.views import AdminAuthView, FunnelView, ProductStatView

urlpatterns = [
    path("auth", AdminAuthView.as_view(), name="admin-auth"),
    path("funnel", FunnelView.as_view(), name="admin-funnel"),
    path("products", ProductStatView.as_view(), name="admin-products"),
]
