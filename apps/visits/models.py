import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

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
    # 연령대·성별은 Visit이 갖는다. 같은 사람이 다음 방문에서 다르게 답할 수 있고,
    # 여기에 두면 마지막 입력이 과거 방문의 코호트 집계까지 소급해서 바꾼다.
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
    # 랜딩의 "당신의 번호를 등록할게요" N.014. 매장별 일련번호이며 이어하기에서는 재발급하지 않는다.
    muse_no = models.PositiveIntegerField()
    age_band = models.CharField(max_length=10, choices=AgeBand.choices, blank=True)
    gender = models.CharField(max_length=10, choices=Gender.choices, blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    # 만료와 이어하기의 기준 시각. 인증을 통과한 요청마다 갱신하되, 매번 쓰면
    # SQLite 쓰기 잠금이 늘어나므로 VISIT_TOUCH_INTERVAL 간격으로 억제한다.
    last_seen_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    # 퇴장을 누르지 않고 방치돼 서버가 닫은 방문. 평균 체류시간과 리포트 완료율의 분모에서 뺀다.
    is_auto_closed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    # updated_at은 last_seen_at과 다르다 — 저장이 일어난 시각(ended_at 기록 등)이고,
    # last_seen_at은 "손님이 아직 관람 중"인지 판정하려고 /events·/chat에서만 갱신하는 값이다.
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["visitor", "ended_at"])]

    def __str__(self) -> str:
        state = "종료" if self.ended_at else "진행 중"
        return f"Visit({self.id}, {state})"

    @property
    def muse_label(self) -> str:
        return f"N.{self.muse_no:03d}"

    @property
    def is_open(self) -> bool:
        """관람이 진행 중인가. 이벤트·대화를 더 쌓아도 되는지의 기준이다."""
        return self.ended_at is None

    @property
    def is_expired(self) -> bool:
        """토큰이 죽었는가. 마지막 활동 이후로 잰다.

        입장 시각으로 재면 3시간을 넘긴 순간 관람 중에도 토큰이 끊긴다. 매장에서
        오래 머무는 손님이 정상인 서비스라 그 편이 더 자주 틀린다. 관람 종료 여부와는
        무관하다 — 퇴장 뒤에도 화보를 만들고 다시 돌려야 하기 때문이다.

        last_seen_at은 인증을 통과한 요청마다 갱신되므로(services.touch),
        "브라우저를 닫고 3시간"이 곧 만료다.
        """
        return timezone.now() - self.last_seen_at >= settings.VISIT_STALE_AFTER
