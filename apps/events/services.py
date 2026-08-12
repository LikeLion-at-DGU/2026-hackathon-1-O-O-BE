"""이벤트 적립. 저장은 append-only이고 event_id로 멱등성을 보장한다."""

from uuid import uuid4

from django.utils import timezone

from apps.catalog.models import Product, Scene
from apps.events.models import Event
from apps.visits.models import Visit


def record(
    visit: Visit,
    event_type: str,
    *,
    scene: Scene | None = None,
    product: Product | None = None,
    metadata: dict | None = None,
) -> Event:
    """서버가 직접 남기는 이벤트.

    store_enter / visit_start / visit_end는 클라이언트가 보내지 않고 서버가 만든다.
    둘 다 보내면 퍼널의 분모가 두 배가 되기 때문이다. 서버 생성이라
    client_timestamp도 서버 시각을 쓴다.
    """
    return Event.objects.create(
        event_id=uuid4(),
        visit=visit,
        event_type=event_type,
        scene=scene,
        product=product,
        client_timestamp=timezone.now(),
        metadata=metadata or {},
    )
