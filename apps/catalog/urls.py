from django.urls import path

from apps.catalog.views import ProductDetailView

urlpatterns = [
    path("products/<str:product_id>", ProductDetailView.as_view(), name="product-detail"),
]
