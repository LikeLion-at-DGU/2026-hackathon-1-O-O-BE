"""방문자 식별과 Visit 수명 관리.

익명 UUID가 하는 일이 세 가지라서 이 파일이 존재한다.
1) 로그인 없이 쓰게 하는 편의성
2) 이탈 복구 — 퇴장을 누르기 전에 창을 닫아도 다시 들어오면 그 Visit을 이어받는다
3) 이벤트 연결 키 겸 코호트 집계 단위
"""

from uuid import UUID

from django.conf import settings
from django.db.models import Count, F
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
    """이어받을 Visit을 찾고, 그 과정에서 만료된 미종료 Visit을 정리한다.

    만료를 배치 스케줄러로 돌리지 않고 여기서 계산한다. 판정 시점이 입장 시점
    하나뿐이라 스케줄러를 띄울 이유가 없다.
    """
    resumable = None

    for visit in visitor.visits.filter(ended_at__isnull=True).order_by("-started_at"):
        if resumable is None and not visit.is_expired:
            resumable = visit
        else:
            expire(visit)

    return resumable


def expire(visit: Visit, *, auto_closed: bool = True) -> None:
    """퇴장을 누르지 않고 방치된 Visit을 닫는다. 리포트는 만들지 않는다.

    auto_closed는 평균 체류시간·리포트 완료율 집계에서 이 방문을 빼기 위한 표시다.
    사용자가 이어하기 모달에서 "새로 시작"을 고른 경우는 방치가 아니므로 False로 닫는다.
    """
    visit.ended_at = timezone.now()
    visit.is_auto_closed = auto_closed
    visit.save(update_fields=["ended_at", "is_auto_closed", "updated_at"])


def issue_muse_no(store: Store) -> int:
    """매장 카운터를 올려 뮤즈 번호를 발급한다. 호출자가 트랜잭션 안이어야 한다.

    SQLite에는 select_for_update가 없어서 F() 갱신에 기댄다. 연결이
    transaction_mode=IMMEDIATE라 트랜잭션 시작 시점에 쓰기 락을 잡으므로,
    동시에 입장해도 같은 번호가 두 번 나가지 않는다.
    """
    Store.objects.filter(pk=store.pk).update(muse_counter=F("muse_counter") + 1)
    return Store.objects.values_list("muse_counter", flat=True).get(pk=store.pk)


def start(visitor: Visitor, store: Store, *, age_band: str = "", gender: str = "") -> Visit:
    """새 Visit + 토큰 + 뮤즈 번호 발급. 관람의 시작점 이벤트도 서버가 남긴다."""
    visit = Visit.objects.create(
        visitor=visitor,
        store=store,
        muse_no=issue_muse_no(store),
        age_band=age_band,
        gender=gender,
    )
    record(visit, EventType.STORE_ENTER)
    record(visit, EventType.VISIT_START)
    return visit


def touch(visit: Visit) -> None:
    """만료·이어하기의 기준 시각을 갱신한다.

    인증을 통과한 요청마다 불리므로 매번 저장하면 SQLite 쓰기가 요청 수만큼 늘어난다.
    만료 기준이 3시간인데 몇 분의 오차는 의미가 없으므로 간격을 두고 억제한다.
    억제 폭만큼 유효 시간이 짧아지지만 최대 VISIT_TOUCH_INTERVAL이다.
    """
    if timezone.now() - visit.last_seen_at < settings.VISIT_TOUCH_INTERVAL:
        return
    visit.last_seen_at = timezone.now()
    visit.save(update_fields=["last_seen_at", "updated_at"])


def summarize(visit: Visit) -> dict:
    """이어하기 모달에 "3개 상품을 보던 중이었어요"를 띄우기 위한 요약."""
    viewed = visit.events.filter(event_type=EventType.PRODUCT_VIEW).aggregate(
        count=Count("product_id", distinct=True)
    )
    return {
        "started_at": visit.started_at,
        "products_viewed": viewed["count"],
        "message_count": visit.chat_logs.count(),
    }
