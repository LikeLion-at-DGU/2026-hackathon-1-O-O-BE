from rest_framework import serializers

from apps.catalog.serializers import SceneSerializer, StoreBriefSerializer
from apps.visits.models import AgeBand, Gender


class EnterRequestSerializer(serializers.Serializer):
    """연령대·성별은 건너뛰기를 허용하므로 둘 다 선택이다."""

    age_band = serializers.ChoiceField(choices=AgeBand.choices, required=False, allow_blank=True)
    gender = serializers.ChoiceField(choices=Gender.choices, required=False, allow_blank=True)
    # 이어하기 모달에서 "새로 시작"을 눌렀을 때만 true로 온다.
    force_new = serializers.BooleanField(required=False, default=False)


class ResumedVisitSerializer(serializers.Serializer):
    started_at = serializers.DateTimeField()
    products_viewed = serializers.IntegerField()
    message_count = serializers.IntegerField()


class EnterResponseSerializer(serializers.Serializer):
    """문서용 스키마. anonymous_uuid와 resumed_visit은 해당 상황에서만 내려간다."""

    anonymous_uuid = serializers.UUIDField(required=False, help_text="신규 발급될 때만 포함")
    visit_id = serializers.CharField()
    visit_token = serializers.CharField()
    store = StoreBriefSerializer()
    scenes = SceneSerializer(many=True)
    resumed = serializers.BooleanField(help_text="진행 중이던 Visit을 이어받았는지")
    resumed_visit = ResumedVisitSerializer(required=False, help_text="resumed=true일 때만 포함")
