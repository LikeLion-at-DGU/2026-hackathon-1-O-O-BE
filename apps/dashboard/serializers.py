from rest_framework import serializers


class AdminAuthSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)


class AdminAuthResponseSerializer(serializers.Serializer):
    access_token = serializers.CharField()
    expires_in = serializers.IntegerField()
    store_ids = serializers.ListField(child=serializers.CharField())


class FunnelStageSerializer(serializers.Serializer):
    key = serializers.CharField()
    label = serializers.CharField()
    visits = serializers.IntegerField()
    rate = serializers.FloatField(help_text="입장 대비 비율. 직전 단계 대비가 아니다")


class FunnelSerializer(serializers.Serializer):
    store_id = serializers.CharField()
    stages = FunnelStageSerializer(many=True)
    auto_closed = serializers.IntegerField(help_text="퇴장을 누르지 않아 서버가 닫은 방문")


class ProductStatSerializer(serializers.Serializer):
    """상품 하나의 관심 지표. "오래 봤는데 화보로 안 이어진 상품"을 찾는 표다."""

    product_id = serializers.CharField()
    name = serializers.CharField()
    scene_no = serializers.IntegerField()
    views = serializers.IntegerField()
    dwell_ms = serializers.IntegerField()
    hotspot_clicks = serializers.IntegerField()
    recommendation_impressions = serializers.IntegerField()
    recommendation_clicks = serializers.IntegerField()
    click_rate = serializers.FloatField()
    lookbook_picks = serializers.IntegerField(help_text="완성된 화보에 담긴 횟수")
