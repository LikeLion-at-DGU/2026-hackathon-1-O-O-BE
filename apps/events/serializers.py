from rest_framework import serializers

from apps.events.models import EventType

# 배치 한 번의 상한. 프론트가 오래 모았거나 재시도가 겹쳐도 이 이상은 받지 않는다.
EVENT_BATCH_MAX = 200

# 이벤트마다 대상이 있어야 의미가 생긴다. product_id 없는 product_view는
# 저장돼도 분석에서 조용히 사라지므로, 받는 쪽에서 막는다.
SCENE_REQUIRED_TYPES = frozenset({EventType.SCENE_VIEW, EventType.SCENE_DWELL, EventType.HOTSPOT_CLICK})
PRODUCT_REQUIRED_TYPES = frozenset(
    {
        EventType.PRODUCT_VIEW,
        EventType.PRODUCT_DWELL,
        EventType.PRODUCT_SAVE,
        EventType.RECOMMENDATION_CLICK,
    }
)
DWELL_KEY = "dwell_ms"


class EventItemSerializer(serializers.Serializer):
    """이벤트 한 건. event_id는 클라이언트가 만들고, 서버는 그걸 중복 제거 키로만 쓴다."""

    event_id = serializers.UUIDField()
    event_type = serializers.ChoiceField(choices=EventType.choices)
    client_timestamp = serializers.DateTimeField()
    scene_id = serializers.CharField(required=False, allow_null=True, default=None)
    product_id = serializers.CharField(required=False, allow_null=True, default=None)
    metadata = serializers.DictField(required=False, default=dict)

    def validate(self, attrs: dict) -> dict:
        event_type = attrs["event_type"]
        if event_type in SCENE_REQUIRED_TYPES and not attrs.get("scene_id"):
            raise serializers.ValidationError({"scene_id": [f"{event_type}에는 scene_id가 필요합니다."]})
        if event_type in PRODUCT_REQUIRED_TYPES and not attrs.get("product_id"):
            raise serializers.ValidationError({"product_id": [f"{event_type}에는 product_id가 필요합니다."]})
        self._validate_dwell(attrs["metadata"])
        return attrs

    def _validate_dwell(self, metadata: dict) -> None:
        """체류시간은 관심도 계산에 그대로 쓰이므로 숫자가 아니면 여기서 걸러야 한다.

        문자열이 섞여 들어오면 저장은 되고 분석 단계에서 터진다.
        """
        if DWELL_KEY not in metadata:
            return
        dwell = metadata[DWELL_KEY]
        if isinstance(dwell, bool) or not isinstance(dwell, int) or dwell < 0:
            raise serializers.ValidationError(
                {"metadata": [f"{DWELL_KEY}는 0 이상의 정수(밀리초)여야 합니다."]}
            )


def validate_batch_size(value: list[dict]) -> list[dict]:
    """배치 상한. /events와 /finish(버퍼 동봉) 양쪽이 같은 한도를 써야 한다."""
    if len(value) > EVENT_BATCH_MAX:
        raise serializers.ValidationError(
            f"한 번에 {EVENT_BATCH_MAX}건까지 보낼 수 있습니다. (받은 수: {len(value)})"
        )
    return value


class EventBatchSerializer(serializers.Serializer):
    visit_id = serializers.CharField()
    events = EventItemSerializer(many=True, allow_empty=False)

    def validate_events(self, value: list[dict]) -> list[dict]:
        return validate_batch_size(value)


class EventBatchResultSerializer(serializers.Serializer):
    accepted = serializers.IntegerField(help_text="새로 저장된 이벤트 수")
    duplicated = serializers.IntegerField(help_text="event_id가 이미 있어 무시된 수")
    ignored = serializers.IntegerField(help_text="서버가 직접 만드는 타입이라 버려진 수")
