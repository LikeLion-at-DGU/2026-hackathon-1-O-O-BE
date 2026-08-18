"""진행률·폴링 간격 계산. 순수 함수만 둔다 — 저장소도 시계도 여기서 만지지 않는다.

**워커는 AI 응답을 기다리는 25초 동안 멈춰 있어 진행률을 갱신할 수 없다.** 그대로
두면 35%에서 25초간 얼어붙는다. 그래서 워커는 시작 시각만 남기고, 이 모듈이
폴링에 답할 때 경과 시간으로 그 사이를 채운다.
"""

from dataclasses import dataclass

# 명세 "단계" 표. 프론트는 step 문자열이 아니라 stage 코드로 분기한다 —
# 카피 한 글자만 바꿔도 애니메이션이 깨지면 곤란하다.
STAGE_COMPOSE = "compose"
STAGE_RENDER = "render"
STAGE_FINALIZE = "finalize"

STAGE_STEPS = {
    STAGE_COMPOSE: "화보를 준비하는 중",
    STAGE_RENDER: "패디가 셔터를 누르는 중",
    STAGE_FINALIZE: "화보를 마무리하는 중",
}

PROGRESS_QUEUED = 0.10
PROGRESS_RENDER_START = 0.35
# 90%를 넘기지 않는다. 예상보다 늦어졌는데 99%에서 멈춰 있으면 더 답답하다.
# 90%에서 대기하다 진짜 끝나면 100%로 점프시킨다.
PROGRESS_CAP = 0.90
PROGRESS_DONE = 1.0

# 폴링 간격은 서버가 매번 내려주고 클라이언트는 따르기만 한다.
# 부하 조절 손잡이를 서버가 쥐고 있어서 데모 당일 사람이 몰려도 배포 없이 대응할 수 있다.
POLL_SLOW_MS = 3000  # 초반 — 어차피 안 끝난다
POLL_FAST_MS = 1200  # 완료 임박
POLL_SWITCH_SEC = 15


@dataclass(frozen=True)
class Progress:
    progress: float
    stage: str

    @property
    def step(self) -> str:
        return STAGE_STEPS[self.stage]


def interpolate(*, is_running: bool, is_done: bool, elapsed_sec: float, expected_sec: int) -> Progress:
    """경과 시간으로 진행률을 메운다. 끝났으면 100%, 아직이면 90%까지만 올린다."""
    if is_done:
        return Progress(progress=PROGRESS_DONE, stage=STAGE_FINALIZE)
    if not is_running:
        return Progress(progress=PROGRESS_QUEUED, stage=STAGE_COMPOSE)

    span = PROGRESS_CAP - PROGRESS_RENDER_START
    ratio = min(elapsed_sec / expected_sec, 1.0) if expected_sec > 0 else 1.0
    value = round(PROGRESS_RENDER_START + span * ratio, 2)
    return Progress(progress=value, stage=_stage_of(value))


def poll_after_ms(elapsed_sec: float) -> int:
    """완료가 가까워지면 더 자주 묻게 한다."""
    return POLL_FAST_MS if elapsed_sec >= POLL_SWITCH_SEC else POLL_SLOW_MS


def _stage_of(progress: float) -> str:
    if progress < PROGRESS_RENDER_START:
        return STAGE_COMPOSE
    if progress < PROGRESS_CAP:
        return STAGE_RENDER
    return STAGE_FINALIZE
