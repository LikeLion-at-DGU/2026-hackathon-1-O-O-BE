"""화보 생성 워커.

**뷰에서 직접 생성하지 않는다.** 15~40초짜리 호출이 gunicorn 워커를 물면 동시
2명에 서비스가 멈춘다.

지금은 `/finish`와 같은 스레드 방식이다. 벤더가 정해지면 Celery로 옮겨야 한다 —
스레드로는 벤더 동시 한도(`IMAGEGEN_SEMAPHORE`)를 지킬 수 없고 재시도도 못 한다.
"""

import logging
import threading
import time
from pathlib import Path

from django.conf import settings
from django.db import connection

from apps.lookbook import jobs, prompts, snapshot, storage
from apps.lookbook.models import Lookbook, LookbookStatus
from common import imagegen

logger = logging.getLogger(__name__)

FAKE_IMAGE_URL = "/media/lookbooks/placeholder.png"
REFERENCE_TIMEOUT_SEC = 5


def enqueue(lookbook: Lookbook) -> None:
    threading.Thread(target=run, args=(lookbook.pk,), daemon=True).start()


def run(share_slug: str) -> None:
    """① 진행률 기록 → ② 생성 → ③ 이미지 저장 → ④ DB ready 순서다.

    ③④ 순서를 뒤집으면 안 된다. DB가 ready인데 이미지가 아직 없으면 사용자가 404를
    본다. 반대 순서는 몇 밀리초 더 기다릴 뿐이라 안전하다.
    """
    try:
        lookbook = Lookbook.objects.get(pk=share_slug)
        _mark_processing(lookbook)
        image_url, size = _generate(lookbook)
        _mark_ready(lookbook, image_url, size)
    except Exception as error:
        logger.exception("화보 생성 실패: %s", share_slug)
        _mark_failed(share_slug, error)
    finally:
        connection.close()


def _mark_processing(lookbook: Lookbook) -> None:
    lookbook.status = LookbookStatus.PROCESSING
    lookbook.save(update_fields=["status", "updated_at"])
    state = jobs.read(lookbook.job_id) or _state_of(lookbook)
    state.status = jobs.STATUS_PROCESSING
    state.started_at = time.time()  # 진행률 보간의 기준. 워커는 이 값만 남긴다
    jobs.write(state)


def _generate(lookbook: Lookbook) -> tuple[str, tuple[int, int]]:
    """사진·마스크·레퍼런스를 재료로 화보를 합성하고 (URL, 크기)를 돌려준다.

    LOOKBOOK_FAKE_AI=True면 벤더를 부르지 않는다. 키가 없거나 크레딧을 아껴야 하는
    날에도 로딩 화면과 완료 화면 전체를 눌러볼 수 있어야 한다.
    """
    if settings.LOOKBOOK_FAKE_AI:
        time.sleep(settings.LOOKBOOK_FAKE_DELAY_SEC)
        return FAKE_IMAGE_URL, settings.LOOKBOOK_IMAGE_SIZE

    photo = storage.read_bytes(lookbook.photo_key)
    # 마스크가 없어도 생성은 된다. 체형 보존이 약해질 뿐이다.
    mask = storage.read_bytes(lookbook.mask_key) if lookbook.mask_key else None
    references = _references(lookbook)

    png = imagegen.edit(
        photo=photo,
        mask=mask,
        references=references,
        prompt=prompts.build(
            mood=snapshot.mood_of(lookbook.mood_payload),
            composition_prompt=lookbook.composition.prompt if lookbook.composition else "",
            product_names=_product_names(lookbook),
            venue=settings.LOOKBOOK_VENUE,
            season=settings.LOOKBOOK_SEASON,
            seed=lookbook.mood_payload.get(snapshot.META_KEY, {}).get("seed", 0),
            attempt=lookbook.attempt,
            has_reference=bool(references),
        ),
    )

    url = storage.save_public(f"{storage.LOOKBOOK_PREFIX}/{lookbook.share_slug}.png", png)
    return url, imagegen.size_of(png)


def _references(lookbook: Lookbook) -> list[bytes]:
    """레이아웃 참조 이미지. **없으면 빈 목록을 준다 — 대충 채우지 않는다.**

    기획이 Composition.reference_url을 비워두면 참조 없이 생성한다. 못 읽는 주소도
    마찬가지다. 여기서 예외를 던지면 레퍼런스 하나 때문에 화보 전체가 실패한다.
    """
    source = lookbook.composition.reference_url if lookbook.composition else ""
    if not source:
        return []
    try:
        return [_fetch(source)]
    except Exception:
        logger.warning("레퍼런스를 읽지 못해 참조 없이 생성합니다: %s", source)
        return []


def _fetch(source: str) -> bytes:
    """레퍼런스는 미디어 경로(/media/...)나 외부 URL 둘 다 올 수 있다."""
    if source.startswith(("http://", "https://")):
        import urllib.request

        with urllib.request.urlopen(source, timeout=REFERENCE_TIMEOUT_SEC) as response:
            return response.read()

    relative = source.removeprefix(settings.MEDIA_URL).removeprefix("/")
    return (Path(settings.MEDIA_ROOT) / relative).read_bytes()


def _product_names(lookbook: Lookbook) -> list[str]:
    """상품 이름을 그대로 프롬프트에 넣는다. id만 주면 벤더가 형태를 지어낸다."""
    from apps.catalog.models import Product

    ordered = Product.objects.filter(id__in=lookbook.product_ids)
    return [product.name for product in ordered]


def _mark_ready(lookbook: Lookbook, image_url: str, size: tuple[int, int]) -> None:
    lookbook.image_url = image_url  # ★ 이미지 먼저
    # 설정값이 아니라 벤더가 실제로 준 크기다. 둘이 어긋나면 완료 화면이 튄다.
    lookbook.width, lookbook.height = size
    lookbook.status = LookbookStatus.READY  # ★ 완료 표시는 맨 마지막
    lookbook.save(update_fields=["image_url", "width", "height", "status", "updated_at"])

    state = jobs.read(lookbook.job_id) or _state_of(lookbook)
    state.status = jobs.STATUS_READY
    jobs.write(state)


def _mark_failed(share_slug: str, error: Exception) -> None:
    """실패 원인을 그대로 남긴다. 정책 차단을 재시도 가능으로 뭉뚱그리면 사용자가
    재생성 3회를 헛되이 쓰고 비용도 그만큼 나간다."""
    error_code = getattr(error, "error_code", jobs.UPSTREAM_ERROR)
    lookbook = Lookbook.objects.filter(pk=share_slug).first()
    if lookbook is None:
        return
    lookbook.status = LookbookStatus.FAILED
    lookbook.error_code = error_code
    lookbook.save(update_fields=["status", "error_code", "updated_at"])

    state = jobs.read(lookbook.job_id) or _state_of(lookbook)
    state.status = jobs.STATUS_FAILED
    state.error_code = error_code
    jobs.write(state)


def _state_of(lookbook: Lookbook) -> jobs.JobState:
    """캐시가 비었을 때(TTL 만료·재시작) 다시 만든다."""
    return jobs.JobState(
        job_id=lookbook.job_id,
        share_slug=lookbook.share_slug,
        attempt=lookbook.attempt,
    )
