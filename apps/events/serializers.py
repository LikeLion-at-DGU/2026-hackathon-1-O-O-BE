from rest_framework import serializers

from apps.events.models import EventType


class EventItemSerializer(serializers.Serializer):
    """이벤트 한 건. event_id는 클라이언트가 만들고, 서버는 그걸 중복 제거 키로만 쓴다."""

    event_id = serializers.UUIDField()
    event_type = serializers.ChoiceField(choices=EventType.choices)
    client_timestamp = serializers.DateTimeField()
    scene_id = serializers.CharField(required=False, allow_null=True, default=None)
    product_id = serializers.CharField(required=False, allow_null=True, default=None)
    metadata = serializers.DictField(required=False, default=dict)


class EventBatchSerializer(serializers.Serializer):
    visit_id = serializers.CharField()
    events = EventItemSerializer(many=True, allow_empty=False)


class EventBatchResultSerializer(serializers.Serializer):
    accepted = serializers.IntegerField(help_text="새로 저장된 이벤트 수")
    duplicated = serializers.IntegerField(help_text="event_id가 이미 있어 무시된 수")
    ignored = serializers.IntegerField(help_text="서버가 직접 만드는 타입이라 버려진 수")
