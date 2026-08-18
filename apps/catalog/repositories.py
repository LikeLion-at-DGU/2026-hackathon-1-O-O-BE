"""매장·전시존 조회. 매장이 하나로 고정이라 조회 지점을 여기 한 곳으로 모은다."""

from django.conf import settings
from rest_framework.exceptions import APIException

from apps.catalog.models import Scene, Store


class StoreNotSeeded(APIException):
    """설정된 기본 매장이 DB에 없을 때. 클라이언트 잘못이 아니라 서버 데이터 문제다."""

    status_code = 500
    default_code = "INTERNAL_ERROR"
    default_detail = "기본 매장 데이터가 없습니다. `manage.py seed_demo`를 먼저 실행하세요."


def get_default_store() -> Store:
    store = Store.objects.filter(pk=settings.DEFAULT_STORE_ID).first()
    if store is None:
        raise StoreNotSeeded()
    return store


def scenes_with_products(store: Store) -> list[Scene]:
    """전시존 + 각 존의 상품 목록. 목록 화면은 이 한 번의 조회로 끝난다(N+1 방지)."""
    return list(store.scenes.prefetch_related("products"))
