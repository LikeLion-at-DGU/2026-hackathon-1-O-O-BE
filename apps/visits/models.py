import uuid

from django.db import models

from common.ids import gen_id, gen_visit_token


def new_visit_id() -> str:
    """마이그레이션이 직렬화할 수 있어야 하므로 lambda가 아닌 이름 있는 함수로 둔다."""
    return gen_id("v")


class AgeBand(models.TextChoices):
    TEENS = "10s", "10대"
    TWENTIES = "20s", "20대"
    THIRTIES = "30s", "30대"
    FORTIES = "40s", "40대"
    FIFTIES_PLUS = "50s+", "50대 이상"


class Gender(models.TextChoices):
    FEMALE = "female", "여성"
    MALE = "male", "남성"
    OTHER = "other", "기타"
    NA = "na", "응답 안 함"


class Visitor(models.Model):
    """익명 방문자. 실명 정보를 받지 않고 UUID만 가진다.

    UUID가 하는 일 세 가지: 로그인 없는 편의성, 이탈 복구(진행 중 Visit 이어받기),
    이벤트 연결 키 겸 코호트 집계 단위.
    """

    anonymous_uuid = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    age_band = models.CharField(max_length=10, choices=AgeBand.choices, blank=True)
    gender = models.CharField(max_length=10, choices=Gender.choices, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"Visitor({self.anonymous_uuid})"


class Visit(models.Model):
    """방문 1회. 사람과 매장이 만나는 지점이자 모든 분석의 단위."""

    id = models.CharField(primary_key=True, max_length=32, default=new_visit_id, editable=False)
    visitor = models.ForeignKey(Visitor, related_name="visits", on_delete=models.CASCADE)
    store = models.ForeignKey("catalog.Store", related_name="visits", on_delete=models.PROTECT)
    token = models.CharField(max_length=64, unique=True, default=gen_visit_token, editable=False)
    started_at = models.DateTimeField(auto_now_add=True)
    # 이어하기 판정용. 매 요청마다 갱신하면 SQLite 쓰기가 늘어나므로
    # /events · /chat 처럼 주기적으로 오는 요청에서만 갱신한다.
    last_seen_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    # created_at을 따로 두지 않는다. started_at과 값이 항상 같고, 명세가 쓰는 이름이 started_at이다.
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["visitor", "ended_at"])]

    def __str__(self) -> str:
        state = "종료" if self.ended_at else "진행 중"
        return f"Visit({self.id}, {state})"

    @property
    def is_open(self) -> bool:
        return self.ended_at is None
