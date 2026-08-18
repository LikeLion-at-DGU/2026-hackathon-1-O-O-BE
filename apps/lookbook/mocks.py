"""폴링 목(mock). 화보 생성 워커가 붙기 전에 프론트가 P02-c·P03을 만들 수 있게 한다.

명세 착수 순서의 "5. jobs 목(mock)"이 이것이다. 진짜 작업이 없어도 로딩 화면의
진행률·단계 전환·실패 분기를 전부 눌러볼 수 있어야 한다.

**DEBUG일 때만 동작한다.** 운영에서 job_mock으로 시작하는 id를 넣어도 그냥 404다.
"""

import time

from django.conf import settings

from apps.lookbook import jobs
from apps.lookbook.jobs import JobState

PREFIX = "job_mock"

# id 뒤에 붙이는 시나리오. 프론트가 분기 3개를 다 확인할 수 있어야 한다.
SCENARIO_FAILED = "failed"  # 재시도 가능 — [다시 시도], 횟수 차감 없음
SCENARIO_BLOCKED = "blocked"  # 재시도 불가 — 다시 촬영 안내
MOCK_SHARE_SLUG = "look-mock01"


def apply(job_id: str, state: JobState | None) -> JobState | None:
    """목 작업이면 없을 때 만들어 주고, 시간이 지났으면 다음 상태로 넘긴다."""
    if not _is_mock(job_id):
        return state
    if state is None:
        return _start(job_id)
    return _advance(state)


def _is_mock(job_id: str) -> bool:
    return settings.DEBUG and job_id.startswith(PREFIX)


def _start(job_id: str) -> JobState:
    """첫 폴링 시각을 시작점으로 잡는다. 그래야 진행률이 0부터 올라간다."""
    if job_id.endswith(SCENARIO_BLOCKED):
        return jobs.write(
            JobState(
                job_id=job_id,
                share_slug=MOCK_SHARE_SLUG,
                status=jobs.STATUS_FAILED,
                error_code=jobs.BLOCKED_ERROR,
            )
        )
    if job_id.endswith(SCENARIO_FAILED):
        return jobs.write(
            JobState(
                job_id=job_id,
                share_slug=MOCK_SHARE_SLUG,
                status=jobs.STATUS_FAILED,
                error_code="GEN_TIMEOUT",
            )
        )
    return jobs.write(
        JobState(
            job_id=job_id,
            share_slug=MOCK_SHARE_SLUG,
            status=jobs.STATUS_PROCESSING,
            started_at=time.time(),
        )
    )


def _advance(state: JobState) -> JobState:
    """예상 시간이 지나면 완료로 넘긴다. 실제 워커가 ready를 쓰는 자리를 흉내 낸다."""
    if state.is_running and state.elapsed_sec >= settings.LOOKBOOK_EXPECTED_SEC:
        state.status = jobs.STATUS_READY
        return jobs.write(state)
    return state
