from rest_framework import serializers

from apps.catalog.models import PresetKey, Product, Scene
from apps.chat.models import ActionType, ChatLog


class ActionMessageSerializer(serializers.Serializer):
    """표시 문구(content)는 받지 않는다. 서버가 만든다."""

    visit_id = serializers.CharField()
    type = serializers.ChoiceField(choices=ActionType.choices)
    scene_id = serializers.CharField(required=False, allow_null=True, default=None)
    product_id = serializers.CharField(required=False, allow_null=True, default=None)
    preset_key = serializers.ChoiceField(
        choices=PresetKey.choices, required=False, allow_null=True, default=None
    )

    def validate(self, attrs: dict) -> dict:
        action_type = attrs["type"]
        if action_type == ActionType.SCENE_CLICK:
            attrs["scene"] = self._require(Scene, attrs["scene_id"], "scene_id")
            attrs["product"] = None
        else:
            attrs["product"] = self._require(Product, attrs["product_id"], "product_id")
            attrs["scene"] = None
        if action_type == ActionType.PRESET_VIEW and not attrs["preset_key"]:
            raise serializers.ValidationError({"preset_key": ["프리셋 열람에는 preset_key가 필요합니다."]})
        return attrs

    def _require(self, model, object_id: str | None, field: str):
        if not object_id:
            raise serializers.ValidationError({field: ["이 값이 필요합니다."]})
        instance = model.objects.filter(id=object_id).first()
        if instance is None:
            raise serializers.ValidationError({field: [f"존재하지 않습니다: {object_id}"]})
        return instance


class ChatMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChatLog
        fields = ("message_id", "role", "content", "created_at")


class ContextSerializer(serializers.Serializer):
    scene_id = serializers.CharField(allow_null=True)
    product_id = serializers.CharField(allow_null=True)


class TimelineSerializer(serializers.Serializer):
    messages = ChatMessageSerializer(many=True)
    current_context = ContextSerializer()


class ChatContextSerializer(serializers.Serializer):
    scene_id = serializers.CharField(required=False, allow_null=True, default=None)
    product_id = serializers.CharField(required=False, allow_null=True, default=None)


class ChatRequestSerializer(serializers.Serializer):
    """context는 선택이다. 생략하면 서버가 최근 클릭 기준으로 문맥을 잡는다."""

    visit_id = serializers.CharField()
    message = serializers.CharField(max_length=500)
    context = ChatContextSerializer(required=False)
