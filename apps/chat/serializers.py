from rest_framework import serializers

from apps.catalog.models import PresetKey, Product, Scene
from apps.chat.models import ActionType, ChatLog

ANSWER_TYPES = (ActionType.HYPOTHESIS_YES, ActionType.HYPOTHESIS_NO, ActionType.CHOICE)
CAMP_OPTIONS = ("use_daily", "use_special", "color_neutral", "color_vivid", "browse_only")


class ActionMessageSerializer(serializers.Serializer):
    """표시 문구(content)는 받지 않는다. 서버가 만든다."""

    visit_id = serializers.CharField()
    type = serializers.ChoiceField(choices=ActionType.choices)
    scene_id = serializers.CharField(required=False, allow_null=True, default=None)
    product_id = serializers.CharField(required=False, allow_null=True, default=None)
    preset_key = serializers.ChoiceField(
        choices=PresetKey.choices, required=False, allow_null=True, default=None
    )
    reply_to = serializers.CharField(required=False, allow_null=True, default=None)
    option = serializers.ChoiceField(
        choices=[(value, value) for value in CAMP_OPTIONS],
        required=False,
        allow_null=True,
        default=None,
    )

    def validate(self, attrs: dict) -> dict:
        action_type = attrs["type"]
        attrs["scene"] = None
        attrs["product"] = None

        if action_type in ANSWER_TYPES:
            return self._validate_answer(attrs)
        if action_type == ActionType.SCENE_CLICK:
            attrs["scene"] = self._require(Scene, attrs["scene_id"], "scene_id")
            return attrs

        attrs["product"] = self._require(Product, attrs["product_id"], "product_id")
        if action_type == ActionType.PRESET_VIEW and not attrs["preset_key"]:
            raise serializers.ValidationError({"preset_key": ["프리셋 열람에는 preset_key가 필요합니다."]})
        return attrs

    def _validate_answer(self, attrs: dict) -> dict:
        """트리거 응답은 어느 가설에 답하는지 밝혀야 한다 (중복 클릭·시차 방어)."""
        if not attrs["reply_to"]:
            raise serializers.ValidationError({"reply_to": ["어느 가설에 답하는지 필요합니다."]})
        if attrs["type"] == ActionType.CHOICE and not (attrs["product_id"] or attrs["option"]):
            raise serializers.ValidationError(
                {"option": ["2택 선택에는 product_id 또는 option이 필요합니다."]}
            )
        if attrs["product_id"]:
            attrs["product"] = self._require(Product, attrs["product_id"], "product_id")
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


class CurrentContextSerializer(serializers.Serializer):
    """응답용. 가장 최근 클릭된 진열대·상품이며 둘 다 없을 수 있다."""

    scene_id = serializers.CharField(allow_null=True)
    product_id = serializers.CharField(allow_null=True)


class PendingActionSerializer(serializers.Serializer):
    kind = serializers.CharField()
    reply_to = serializers.CharField()
    options = serializers.ListField(child=serializers.DictField())


class TimelineSerializer(serializers.Serializer):
    messages = ChatMessageSerializer(many=True)
    current_context = CurrentContextSerializer()
    pending_action = PendingActionSerializer(allow_null=True)


class ActionResultSerializer(serializers.Serializer):
    """POST /chat/messages 응답. 이번 호출로 쌓인 말풍선 전부를 돌려준다."""

    messages = ChatMessageSerializer(many=True)
    recommendations = serializers.ListField(child=serializers.DictField())
    profile_completion = serializers.FloatField()


class TimelineQuerySerializer(serializers.Serializer):
    visit_id = serializers.CharField()


class ContextInputSerializer(serializers.Serializer):
    """요청용 문맥 지정. 없는 id를 받으면 문맥이 조용히 비므로 존재를 검증한다."""

    scene_id = serializers.CharField(required=False, allow_null=True, default=None)
    product_id = serializers.CharField(required=False, allow_null=True, default=None)

    def validate_scene_id(self, value: str | None) -> str | None:
        return self._assert_exists(Scene, value, "scene_id")

    def validate_product_id(self, value: str | None) -> str | None:
        return self._assert_exists(Product, value, "product_id")

    def _assert_exists(self, model, object_id: str | None, field: str) -> str | None:
        if object_id and not model.objects.filter(id=object_id).exists():
            raise serializers.ValidationError(f"존재하지 않습니다: {object_id}")
        return object_id


class ChatRequestSerializer(serializers.Serializer):
    """context는 선택이다. 생략하면 서버가 최근 클릭 기준으로 문맥을 잡는다."""

    visit_id = serializers.CharField()
    message = serializers.CharField(max_length=500)
    context = ContextInputSerializer(required=False)
