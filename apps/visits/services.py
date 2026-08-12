"""방문자 식별과 Visit 수명 관리.

익명 UUID가 하는 일이 세 가지라서 이 파일이 존재한다.
1) 로그인 없이 쓰게 하는 편의성
2) 이탈 복구 — 퇴장을 누르기 전에 창을 닫아도 다시 들어오면 그 Visit을 이어받는다
3) 이벤트 연결 키 겸 코호트 집계 단위
"""

from uuid import UUID

from django.conf import settings
from django.db.models import Count
from django.utils import timezone

from apps.catalog.models import Store
from apps.events.models import EventType
from apps.events.services import record
from apps.visits.models import Visit, Visitor


def parse_uuid(raw: str | None) -> UUID | None:
    """클라이언트가 보낸 X-Anonymous-UUID. 형식이 깨졌으면 없는 것으로 취급한다.

    위조·오타로 400을 주면 입장 자체가 막혀버린다. 새로 발급해주는 편이 안전하다.
    """
    if not raw:
        return None
    try:
        return UUID(raw)
    except ValueError:
        return None


def resolve_or_issue(anonymous_uuid: UUID | None) -> tuple[Visitor, bool]:
    """방문자를 찾고 없으면 발급한다. (visitor, 신규 발급 여부)를 준다."""
    if anonymous_uuid:
        visitor = Visitor.objects.filter(pk=anonymous_uuid).first()
        if visitor is not None:
            return visitor, False
    return Visitor.objects.create(), True


def find_resumable(visitor: Visitor) -> Visit | None:
    """이어받을 Visit을 찾고, 그 과정에서 오래된 미종료 Visit을 정리한다.

    만료를 배치 스케줄러로 돌리지 않고 여기서 계산한다. 판정 시점이 입장 시점
    하나뿐이라 스케줄러를 띄울 이유가 없다.
    """
    threshold = timezone.now() - settings.RESUME_WINDOW
    resumable = None

    for visit in visitor.visits.filter(ended_at__isnull=True).order_by("-last_seen_at"):
        if resumable is None and visit.last_seen_at >= threshold:
            resumable = visit
        else:
            expire(visit)

    return resumable


def expire(visit: Visit) -> None:
    """퇴장을 누르지 않고 방치된 Visit을 닫는다. 리포트는 만들지 않는다."""
    visit.ended_at = timezone.now()
    visit.save(update_fields=["ended_at", "updated_at"])


def start(visitor: Visitor, store: Store) -> Visit:
    """새 Visit + 토큰 발급. 관람의 시작점 이벤트도 서버가 남긴다."""
    visit = Visit.objects.create(visitor=visitor, store=store)
    record(visit, EventType.STORE_ENTER)
    record(visit, EventType.VISIT_START)
    return visit


def touch(visit: Visit) -> None:
    """이어하기 판정 기준 시각을 갱신한다."""
    visit.last_seen_at = timezone.now()
    visit.save(update_fields=["last_seen_at", "updated_at"])


def apply_demographics(visitor: Visitor, age_band: str, gender: str) -> None:
    """연령대·성별은 새로 시작할 때만 반영한다.

    이어하기에서 덮어쓰지 않는 이유는, 이미 답한 사람에게 다시 묻지 않기로 했기 때문이다.
    건너뛰기도 허용하므로 값이 없으면 그대로 둔다.
    """
    updated = []
    if age_band:
        visitor.age_band = age_band
        updated.append("age_band")
    if gender:
        visitor.gender = gender
        updated.append("gender")
    if updated:
        visitor.save(update_fields=[*updated, "updated_at"])


def summarize(visit: Visit) -> dict:
    """이어하기 모달에 "3개 상품을 보던 중이었어요"를 띄우기 위한 요약."""
    viewed = (
        visit.events.filter(event_type=EventType.PRODUCT_VIEW, product__isnull=False)
        .values("product_id")
        .aggregate(count=Count("product_id", distinct=True))
    )
    return {
        "started_at": visit.started_at,
        "products_viewed": viewed["count"] or 0,
        "message_count": visit.chat_logs.count(),
    }
