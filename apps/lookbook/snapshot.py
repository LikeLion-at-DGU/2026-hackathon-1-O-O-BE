"""화보에 박제하는 값. 생성 시점에 한 번 만들고, 조회는 이걸 그대로 낸다.

**무드 산출식을 나중에 튜닝하면 같은 방문도 다른 무드가 나온다.** 공유된 링크를
나중에 열었을 때 내용이 바뀌면 안 되므로, 조회 시점에 재계산하지 않는다.
`reports.payload`를 박제하는 것과 같은 이유다.
"""

from django.conf import settings

MOOD_KEY = "mood"
STATS_KEY = "stats"
META_KEY = "_meta"


def build(report, visit, seed: int) -> dict:
    """생성 요청 시점의 스냅샷. mood·stats·muse_no가 여기서 굳는다."""
    payload = report.payload if isinstance(report.payload, dict) else {}
    return {
        MOOD_KEY: payload.get(MOOD_KEY, {}),
        # 어떤 값을 세는지는 기획 미확정이라 리포트에 있으면 옮기고 없으면 비운다.
        # 억지로 채우면 화면에 틀린 숫자가 박제된다.
        STATS_KEY: payload.get(STATS_KEY, []),
        "muse_no": visit.muse_no,
        "muse_label": visit.muse_label,
        "venue": settings.LOOKBOOK_VENUE,
        "season": settings.LOOKBOOK_SEASON,
        # seed를 안 남기면 나온 결과를 되짚을 수 없다.
        META_KEY: {"seed": seed},
    }


def mood_of(snapshot: dict) -> dict:
    return snapshot.get(MOOD_KEY) or {}


def stats_of(snapshot: dict) -> list:
    stats = snapshot.get(STATS_KEY)
    return stats if isinstance(stats, list) else []
