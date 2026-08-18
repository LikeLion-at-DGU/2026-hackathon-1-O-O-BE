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
    """문서용 스키마. resumed_visit만 해당 상황에서 추가로 내려간다."""

    anonymous_uuid = serializers.UUIDField(help_text="항상 포함. 값이 바뀌었으면 클라이언트가 덮어쓴다")
    visit_id = serializers.CharField()
    visit_token = serializers.CharField()
    muse_no = serializers.IntegerField(help_text="이 매장의 몇 번째 뮤즈인지")
    muse_label = serializers.CharField(help_text="랜딩 표기용. 예: N.014")
    store = StoreBriefSerializer()
    scenes = SceneSerializer(many=True)
    is_new = serializers.BooleanField(help_text="이 기기에서 처음 온 방문자인지")
    is_resumed = serializers.BooleanField(help_text="진행 중이던 Visit을 이어받았는지")
    resumed_visit = ResumedVisitSerializer(required=False, help_text="is_resumed=true일 때만 포함")
