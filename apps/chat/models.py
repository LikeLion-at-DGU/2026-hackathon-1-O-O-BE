"""채팅 타임라인. 클릭이 그대로 메시지로 쌓이고, 그게 AI의 문맥이 된다."""

from django.db import models

from common.ids import gen_id


def new_message_id() -> str:
    return gen_id("m")


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
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [models.Index(fields=["visit", "created_at"])]

    def __str__(self) -> str:
        return f"[{self.role}] {self.content[:30]}"
