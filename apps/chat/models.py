"""채팅 타임라인. 클릭이 그대로 메시지로 쌓이고, 그게 AI의 문맥이 된다."""

from django.db import models

from common.ids import gen_id


def new_message_id() -> str:
    return gen_id("m")


class ActionType(models.TextChoices):
    """클릭이 말풍선으로 남는 세 가지 경로."""

    SCENE_CLICK = "scene_click", "진열대 클릭"
    PRODUCT_CLICK = "product_click", "상품 클릭"
    PRESET_VIEW = "preset_view", "프리셋 열람"


class Role(models.TextChoices):
    ASSISTANT = "assistant", "챗봇"
    USER_ACTION = "user_action", "클릭이 남긴 메시지"
    USER = "user", "사용자가 타이핑한 질문"
    PRESET = "preset", "미리 작성된 프리셋 답변"


class ChatLog(models.Model):
    message_id = models.CharField(primary_key=True, max_length=32, default=new_message_id, editable=False)
    visit = models.ForeignKey("visits.Visit", related_name="chat_logs", on_delete=models.CASCADE)
    role = models.CharField(max_length=15, choices=Role.choices)
    content = models.TextField()
    scene = models.ForeignKey(
        "catalog.Scene", related_name="chat_logs", on_delete=models.SET_NULL, null=True, blank=True
    )
    product = models.ForeignKey(
        "catalog.Product", related_name="chat_logs", on_delete=models.SET_NULL, null=True, blank=True
    )
    # 메시지는 한 번 쌓이면 고치지 않는다(append-only). Event와 같은 이유로 updated_at을 두지 않는다.
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [models.Index(fields=["visit", "created_at"])]

    def __str__(self) -> str:
        return f"[{self.role}] {self.content[:30]}"
