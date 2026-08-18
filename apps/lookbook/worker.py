"""화보 생성 워커.

**뷰에서 직접 생성하지 않는다.** 15~40초짜리 호출이 uvicorn 프로세스를 물면 동시
2명에 서비스가 멈춘다.

지금은 `/finish`와 같은 스레드 방식이다. 벤더가 정해지면 Celery로 옮겨야 한다 —
스레드로는 벤더 동시 한도(`IMAGEGEN_SEMAPHORE`)를 지킬 수 없고 재시도도 못 한다.
"""

import logging
import threading
import time

from django.conf import settings
from django.db import connection

from apps.lookbook import jobs
from apps.lookbook.models import Lookbook, LookbookStatus

logger = logging.getLogger(__name__)

FAKE_IMAGE_URL = "/media/lookbooks/placeholder.png"


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
        image_url = _generate(lookbook)
        _mark_ready(lookbook, image_url)
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


def _generate(lookbook: Lookbook) -> str:
    """이미지 생성. 벤더가 정해질 때까지는 가짜 결과를 돌려준다.

    가짜라도 워커·폴링·완료 화면이 전부 실제 경로로 동작하므로, 벤더가 붙을 때
    바꿀 곳이 이 함수 하나로 좁혀진다.
    """
    if not settings.LOOKBOOK_FAKE_AI:
        raise NotImplementedError("이미지 생성 벤더가 아직 연결되지 않았습니다.")
    time.sleep(settings.LOOKBOOK_FAKE_DELAY_SEC)
    return FAKE_IMAGE_URL


def _mark_ready(lookbook: Lookbook, image_url: str) -> None:
    lookbook.image_url = image_url  # ★ 이미지 먼저
    lookbook.status = LookbookStatus.READY  # ★ 완료 표시는 맨 마지막
    lookbook.save(update_fields=["image_url", "status", "updated_at"])

    state = jobs.read(lookbook.job_id) or _state_of(lookbook)
    state.status = jobs.STATUS_READY
    jobs.write(state)


def _mark_failed(share_slug: str, error: Exception) -> None:
    lookbook = Lookbook.objects.filter(pk=share_slug).first()
    if lookbook is None:
        return
    lookbook.status = LookbookStatus.FAILED
    lookbook.error_code = jobs.UPSTREAM_ERROR
    lookbook.save(update_fields=["status", "error_code", "updated_at"])

    state = jobs.read(lookbook.job_id) or _state_of(lookbook)
    state.status = jobs.STATUS_FAILED
    state.error_code = jobs.UPSTREAM_ERROR
    jobs.write(state)


def _state_of(lookbook: Lookbook) -> jobs.JobState:
    """캐시가 비었을 때(TTL 만료·재시작) 다시 만든다."""
    return jobs.JobState(
        job_id=lookbook.job_id,
        share_slug=lookbook.share_slug,
        attempt=lookbook.attempt,
    )
