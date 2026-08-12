from rest_framework import serializers

from apps.catalog.models import Product, Scene, Store


class StoreBriefSerializer(serializers.ModelSerializer):
    store_id = serializers.CharField(source="id")

    class Meta:
        model = Store
        fields = ("store_id", "name")


class ProductBriefSerializer(serializers.ModelSerializer):
    """목록용 간략 정보. 상세 정보는 GET /products/{id}가 준다."""

    product_id = serializers.CharField(source="id")
    thumbnail = serializers.CharField(allow_null=True)

    class Meta:
        model = Product
        fields = ("product_id", "no", "name", "thumbnail", "price")


class SceneSerializer(serializers.ModelSerializer):
    """전시존 구성. 좌표·도면은 내려주지 않는다 — 맵은 프론트가 직접 만든다.

    no를 함께 주는 이유는 챗봇이 "1번 진열대 3번 상품"처럼 번호로 안내해야 하기 때문이다.
    """

    scene_id = serializers.CharField(source="id")
    products = ProductBriefSerializer(many=True)

    class Meta:
        model = Scene
        fields = ("scene_id", "no", "name", "products")
