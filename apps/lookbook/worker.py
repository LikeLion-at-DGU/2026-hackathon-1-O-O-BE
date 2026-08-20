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

from apps.lookbook import compose, jobs, prompts, snapshot, storage
from apps.lookbook.models import Lookbook, LookbookStatus
from common import imagegen

logger = logging.getLogger(__name__)

FAKE_PERSON_COLOR = (209, 205, 199)
REFERENCE_TIMEOUT_SEC = 5
COMPOSE_CUTOUT = "cutout"


def enqueue(lookbook: Lookbook) -> None:
    threading.Thread(target=run, args=(lookbook.pk,), daemon=True).start()


def run(share_slug: str) -> None:
    """① 진행률 기록 → ② 생성 → ③ 이미지 저장 → ④ DB ready 순서다.

    ③④ 순서를 뒤집으면 안 된다. DB가 ready인데 이미지가 아직 없으면 사용자가 404를
    본다. 반대 순서는 몇 밀리초 더 기다릴 뿐이라 안전하다.
    """
    started = time.monotonic()
    try:
        lookbook = Lookbook.objects.get(pk=share_slug)
        # 로그 접두사를 ASCII로 맞춘다. 서버에서 `journalctl | grep lookbook`으로
        # 한 건의 흐름을 통째로 따라갈 수 있어야 한다.
        logger.info(
            "[lookbook %s] 시작 attempt=%s photo=%s mask=%s products=%s",
            share_slug,
            lookbook.attempt,
            lookbook.photo_key,
            lookbook.mask_key or "(없음)",
            lookbook.product_ids,
        )
        _mark_processing(lookbook)
        image_url, size = _generate(lookbook)
        _mark_ready(lookbook, image_url, size)
        logger.info(
            "[lookbook %s] 완료 %.1f초 %sx%s %s",
            share_slug,
            time.monotonic() - started,
            size[0],
            size[1],
            image_url,
        )
    except Exception as error:
        logger.exception(
            "[lookbook %s] 실패 %.1f초 code=%s",
            share_slug,
            time.monotonic() - started,
            getattr(error, "error_code", "UNKNOWN"),
        )
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
        logger.info("[lookbook %s] FAKE_AI 모드 — 벤더를 부르지 않는다", lookbook.share_slug)
        time.sleep(settings.LOOKBOOK_FAKE_DELAY_SEC)
        # 고정 placeholder 파일에 의존하지 않는다. 그 파일이 없는 새 환경(레포를 갓
        # 클론한 리뷰어)에서 화보가 ready인데 이미지만 404가 나는 결함이 있었다.
        # 단색 인물판을 실제 합성·저장 경로에 태워 진짜 파일을 만든다.
        return _finish(lookbook, _fake_person_png(), [])

    photo = storage.read_bytes(lookbook.photo_key)
    # 마스크가 없어도 생성은 된다. 체형 보존이 약해질 뿐이다.
    mask = storage.read_bytes(lookbook.mask_key) if lookbook.mask_key else None
    products = _product_images(lookbook)

    # 누끼 모드: 벤더를 부르지 않고 마스크로 인물만 오려 배경판에 얹는다.
    # 얼굴이 100% 원본이고 공짜이며 즉시 끝난다. 마스크가 없으면 오릴 수가 없어
    # 배경을 새로 그리는 AI 경로로 넘어간다.
    logger.info(
        "[lookbook %s] 재료 photo=%dKB mask=%s products=%d mode=%s",
        lookbook.share_slug,
        len(photo) // 1024,
        f"{len(mask) // 1024}KB" if mask else "없음",
        len(products),
        settings.LOOKBOOK_COMPOSE_MODE,
    )

    if settings.LOOKBOOK_COMPOSE_MODE == COMPOSE_CUTOUT and mask:
        logger.info("[lookbook %s] 누끼 경로 — 벤더 호출 없음", lookbook.share_slug)
        return _finish(lookbook, compose.cutout(photo, mask), products)

    # 순서가 계약이다. prompts._roles()가 "Image 2는 레퍼런스, Image 3은 상품"이라고
    # 말하므로, 여기서 넣는 순서가 바뀌면 모델이 상품을 보존 대상으로 오해한다.
    reference = _reference_image(lookbook)

    logger.info(
        "[lookbook %s] 벤더 호출 model=%s size=%s quality=%s ref=%s",
        lookbook.share_slug,
        settings.LOOKBOOK_IMAGE_MODEL,
        settings.LOOKBOOK_GEN_SIZE,
        settings.LOOKBOOK_GEN_QUALITY,
        "있음" if reference else "없음",
    )
    vendor_started = time.monotonic()

    png = imagegen.edit(
        photo=photo,
        mask=mask,
        references=[item for item in (reference, *products) if item],
        prompt=prompts.build(
            mood=snapshot.mood_of(lookbook.mood_payload),
            composition_prompt=lookbook.composition.prompt if lookbook.composition else "",
            product_names=_product_names(lookbook),
            venue=settings.LOOKBOOK_VENUE,
            season=settings.LOOKBOOK_SEASON,
            seed=lookbook.mood_payload.get(snapshot.META_KEY, {}).get("seed", 0),
            attempt=lookbook.attempt,
            has_reference=bool(reference),
            has_product_image=bool(products),
        ),
    )

    logger.info(
        "[lookbook %s] 벤더 응답 %.1f초 %dKB",
        lookbook.share_slug,
        time.monotonic() - vendor_started,
        len(png) // 1024,
    )

    # 상품을 따로 넘기지 않는다 — 벤더가 이미 인물에게 들려줬다. 또 얹으면 두 개가 된다.
    return _finish(lookbook, png, [])


def _finish(lookbook: Lookbook, person: bytes, products: list[bytes]) -> tuple[str, tuple[int, int]]:
    """인물 이미지를 레이아웃에 얹고 저장한다.

    타이포·프레임·캡션은 여기서 그린다 — 모델에게 글자를 그리게 하면 뭉개지고,
    캡션의 뮤즈 번호는 방문마다 달라야 한다.
    """
    final = compose.build(
        person=person,
        product=products[0] if products else None,
        caption=lookbook.mood_payload,
        size=settings.LOOKBOOK_IMAGE_SIZE,
    )
    logger.info("[lookbook %s] 합성 완료 %dKB", lookbook.share_slug, len(final) // 1024)

    url = storage.save_public(f"{storage.LOOKBOOK_PREFIX}/{lookbook.share_slug}.png", final)
    logger.info("[lookbook %s] 저장 완료 %s", lookbook.share_slug, url)
    return url, imagegen.size_of(final)


def _fake_person_png() -> bytes:
    """FAKE 모드의 인물 대체 이미지. 타이포·캡션 합성은 실제와 동일하게 거친다."""
    from io import BytesIO

    from PIL import Image

    canvas = Image.new("RGB", settings.LOOKBOOK_IMAGE_SIZE, FAKE_PERSON_COLOR)
    buffer = BytesIO()
    canvas.save(buffer, format="PNG")
    return buffer.getvalue()


def _reference_image(lookbook: Lookbook) -> bytes | None:
    """구도 참조 이미지. **없으면 None을 준다 — 대충 채우지 않는다.**

    기획이 Composition.reference_url을 비워두면 참조 없이 생성한다. 못 읽는 주소도
    마찬가지다. 여기서 예외를 던지면 레퍼런스 하나 때문에 화보 전체가 실패한다.
    """
    source = lookbook.composition.reference_url if lookbook.composition else ""
    return _optional(source, "레퍼런스")


def _product_images(lookbook: Lookbook) -> list[bytes]:
    """배경을 제거한 상품 PNG. 이름만 주면 벤더가 가방 모양을 지어낸다.

    파일이 없으면 조용히 건너뛴다 — 상품 사진이 없다고 화보를 못 만들 이유는 없고,
    프롬프트의 상품 이름이 그 자리를 대신한다.
    """
    from apps.catalog.models import Product

    sources = Product.objects.filter(id__in=lookbook.product_ids).values_list("cutout_url", flat=True)
    images = [_optional(source, "상품 컷아웃") for source in sources]
    return [image for image in images if image]


def _optional(source: str, label: str) -> bytes | None:
    """읽히면 바이트, 아니면 None. 재료 하나 때문에 생성 전체가 죽으면 안 된다."""
    if not source:
        return None
    try:
        return _fetch(source)
    except Exception:
        logger.warning("%s를 읽지 못해 빼고 생성합니다: %s", label, source)
        return None


def _fetch(source: str) -> bytes:
    """레퍼런스·컷아웃은 미디어 경로(/media/...)나 외부 URL 둘 다 올 수 있다.

    접두사를 슬래시 없이 비교하는 이유는 MEDIA_URL이 "media/"로 적혀 있어도 Django가
    "/media/"로 정규화하기 때문이다. 어느 쪽으로 적히든 같게 동작해야 한다.

    **MEDIA_ROOT 밖은 읽지 않는다.** 이 값은 DB(Composition.reference_url,
    Product.cutout_url)에서 오고 admin에서 사람이 고칠 수 있다. `../`가 섞이면
    서버의 아무 파일이나 벤더에 업로드될 수 있으므로 경로를 풀어 확인한다.
    """
    if source.startswith(("http://", "https://")):
        import urllib.request

        with urllib.request.urlopen(source, timeout=REFERENCE_TIMEOUT_SEC) as response:
            return response.read()

    media_prefix = settings.MEDIA_URL.strip("/") + "/"
    relative = source.lstrip("/").removeprefix(media_prefix)

    media_root = Path(settings.MEDIA_ROOT).resolve()
    file_path = (media_root / relative).resolve()
    file_path.relative_to(media_root)  # 벗어나면 ValueError → 호출부가 걸러낸다

    return file_path.read_bytes()


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
