"""행동 이벤트 원본. 쌓기만 하고 고치지 않는다(append-only)."""

from django.db import models


class EventType(models.TextChoices):
    # 매장 / 방문 — 서버가 생성한다 (프론트는 보내지 않는다)
    STORE_ENTER = "store_enter", "입장"
    VISIT_START = "visit_start", "방문 시작"
    VISIT_END = "visit_end", "방문 종료"
    # 전시존
    SCENE_VIEW = "scene_view", "전시존 조회"
    SCENE_DWELL = "scene_dwell", "전시존 체류"
    HOTSPOT_CLICK = "hotspot_click", "핫스팟 클릭"
    # 상품 — 취향 분석의 핵심 재료
    PRODUCT_VIEW = "product_view", "상품 조회"
    PRODUCT_DWELL = "product_dwell", "상품 체류"
    # 챗봇
    CHATBOT_OPEN = "chatbot_open", "챗봇 열기"
    QUESTION_SUBMIT = "question_submit", "질문 전송"
    RECOMMENDATION_IMPRESSION = "recommendation_impression", "추천 노출"
    RECOMMENDATION_CLICK = "recommendation_click", "추천 클릭"
    # 화보 — 관람이 끝난 뒤(ended_at 이후)에 일어나는 유일한 이벤트군
    LOOKBOOK_CANDIDATES_VIEW = "lookbook_candidates_view", "화보 후보 조회"
    LOOKBOOK_PRODUCT_SELECT = "lookbook_product_select", "화보 상품 선택"
    PHOTO_CONSENT = "photo_consent", "사진 촬영 동의"
    PHOTO_CAPTURE = "photo_capture", "사진 촬영"
    PHOTO_RETAKE = "photo_retake", "사진 재촬영"
    LOOKBOOK_GENERATE_REQUEST = "lookbook_generate_request", "화보 생성 요청"
    LOOKBOOK_REGENERATE = "lookbook_regenerate", "화보 재생성"
    LOOKBOOK_COMPLETE = "lookbook_complete", "화보 완성"
    LOOKBOOK_SHARE = "lookbook_share", "화보 공유"
    LOOKBOOK_SAVE = "lookbook_save", "화보 저장"


class Event(models.Model):
    event_id = models.UUIDField(primary_key=True)  # 클라이언트 생성. 중복 제거 키
    visit = models.ForeignKey("visits.Visit", related_name="events", on_delete=models.CASCADE)
    event_type = models.CharField(max_length=30, choices=EventType.choices)
    scene = models.ForeignKey(
        "catalog.Scene", related_name="events", on_delete=models.SET_NULL, null=True, blank=True
    )
    product = models.ForeignKey(
        "catalog.Product", related_name="events", on_delete=models.SET_NULL, null=True, blank=True
    )
    client_timestamp = models.DateTimeField()  # 클라에서 일어난 시각
    server_received_at = models.DateTimeField(auto_now_add=True)  # 지연 전송·순서 뒤바뀜 판별용
    metadata = models.JSONField(default=dict)  # dwell_ms 등
    # append-only라 updated_at을 두지 않는다. created_at은 server_received_at과 같은 값이 되므로 생략.

    class Meta:
        indexes = [
            models.Index(fields=["visit", "event_type"]),
            models.Index(fields=["product", "event_type"]),
        ]

    def __str__(self) -> str:
        return f"{self.event_type}({self.visit_id})"
