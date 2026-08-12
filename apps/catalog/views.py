from drf_spectacular.utils import extend_schema
from rest_framework import generics

from api.permissions import IsVisitAuthenticated
from apps.catalog.models import Product
from apps.catalog.serializers import ProductDetailSerializer


@extend_schema(tags=["Product"])
class ProductDetailView(generics.RetrieveAPIView):
    """GET /api/v1/products/{product_id} — 상품 상세.

    상품을 열었다는 사실은 여기서 기록하지 않는다. 기록은 POST /events의
    product_view / product_dwell이 담당한다. 조회와 기록은 분리한다.
    """

    serializer_class = ProductDetailSerializer
    permission_classes = [IsVisitAuthenticated]
    queryset = Product.objects.select_related("scene")
    lookup_url_kwarg = "product_id"
