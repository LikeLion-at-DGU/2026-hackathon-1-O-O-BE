"""화보 생성 작업의 진행 상태 저장소.

**휘발성 데이터는 휘발성 저장소에 둔다.** 화보 하나당 폴링이 8~9번이고, 진행률이
40%였다는 기록은 나중에 아무도 찾지 않는다. 그래서 DB가 아니라 캐시에 둔다.

Django 캐시 프레임워크를 쓰는 이유는 Redis를 붙일 때 `CACHES` 설정만 갈아끼우면
이 모듈이 그대로 동작하기 때문이다.
"""

import time
from dataclasses import asdict, dataclass, field

from django.conf import settings
from django.core.cache import cache

from apps.lookbook import progress as progress_calc

KEY_PREFIX = "lb"

STATUS_QUEUED = "queued"
STATUS_PROCESSING = "processing"
STATUS_READY = "ready"
STATUS_FAILED = "failed"

# 재시도해도 되는 실패와 아닌 실패를 가른다.
# GEN_CONTENT_BLOCKED는 얼굴 사진이 벤더 정책에 걸린 경우라 다시 눌러도 계속 막힌다.
# 이걸 retryable로 두면 사용자가 재생성 3회를 헛되이 쓰고 비용도 그만큼 나간다.
TIMEOUT_ERROR = "GEN_TIMEOUT"
RATE_LIMITED_ERROR = "GEN_RATE_LIMITED"
UPSTREAM_ERROR = "GEN_UPSTREAM"
RETRYABLE_ERRORS = frozenset({TIMEOUT_ERROR, RATE_LIMITED_ERROR, UPSTREAM_ERROR})
BLOCKED_ERROR = "GEN_CONTENT_BLOCKED"


@dataclass
class JobState:
    """캐시에 담기는 값. 폴링 응답이 이걸 그대로 펼친다."""

    job_id: str
    share_slug: str
    attempt: int = 1
    status: str = STATUS_QUEUED
    error_code: str | None = None
    started_at: float | None = None  # AI 호출 시작 unix time. 진행률 보간의 기준
    meta: dict = field(default_factory=dict)

    @property
    def is_running(self) -> bool:
        return self.status == STATUS_PROCESSING and self.started_at is not None

    @property
    def is_done(self) -> bool:
        return self.status == STATUS_READY

    @property
    def elapsed_sec(self) -> float:
        return max(0.0, time.time() - self.started_at) if self.started_at else 0.0

    @property
    def is_retryable(self) -> bool:
        return self.error_code in RETRYABLE_ERRORS


def read(job_id: str) -> JobState | None:
    """없으면 None. TTL이 지났거나 서버를 재시작한 경우다.

    실제 화보 생성이 붙으면 여기서 DB(lookbooks)로 폴백해야 한다. 지금은 그 테이블이
    없으므로 폴백을 흉내 내지 않고 None을 그대로 돌려준다 — 없는 걸 있는 척하면
    프론트가 잘못된 상태를 믿는다.
    """
    payload = cache.get(_key(job_id))
    return JobState(**payload) if payload else None


def write(state: JobState) -> JobState:
    """작업 상태를 갱신한다. TTL은 폴링이 끝나고도 잠깐 남을 만큼만 둔다."""
    cache.set(_key(state.job_id), asdict(state), timeout=settings.LOOKBOOK_JOB_TTL_SEC)
    return state


def as_response(state: JobState) -> dict:
    """폴링 응답 본문. 진행률과 다음 폴링 간격은 매 요청 계산한다."""
    elapsed = state.elapsed_sec
    computed = progress_calc.interpolate(
        is_running=state.is_running,
        is_done=state.is_done,
        elapsed_sec=elapsed,
        expected_sec=settings.LOOKBOOK_EXPECTED_SEC,
    )
    return {
        "job_id": state.job_id,
        "status": state.status,
        "progress": computed.progress,
        "stage": computed.stage,
        "step": computed.step,
        "share_slug": state.share_slug,
        "attempt": state.attempt,
        "error_code": state.error_code,
        "retryable": state.is_retryable,
        "poll_after_ms": progress_calc.poll_after_ms(elapsed),
    }


def _key(job_id: str) -> str:
    return f"{KEY_PREFIX}:{job_id}"
