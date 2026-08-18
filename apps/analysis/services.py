"""관람 종료와 리포트 생성. HTTP 응답 경로와 워커 경로가 여기서 갈린다.

`/finish`는 slug만 즉시 돌려주고, 3~4초 걸리는 분석은 백그라운드 스레드가 맡는다.
Celery를 쓰지 않는 이유는 SQLite + 수 초짜리 작업에 redis·worker·beat 세 프로세스를
띄우면 데모에서 죽을 지점만 늘기 때문이다(`tasks/결정사항.md` §1-4).
"""

import logging
import threading

from django.db import connection, transaction
from django.utils import timezone

from apps.analysis import character, collect, insight, pipeline
from apps.analysis import report as report_builder
from apps.analysis.models import Report, ReportStatus, TasteProfile
from apps.events.models import EventType
from apps.events.services import append_batch, record
from apps.visits.models import Visit

logger = logging.getLogger(__name__)

EMPTY_EVENT_RESULT = {"accepted": 0, "duplicated": 0, "ignored": 0, "rejected": 0}


@transaction.atomic
def finish(visit: Visit, event_items: list[dict]) -> tuple[Report, dict, bool]:
    """① 남은 이벤트 저장 → ② 방문 종료 → ③ 리포트 발급. 한 트랜잭션이다.

    이 순서 덕분에 "이벤트는 저장됐는데 종료가 안 된" 중간 상태가 없고, 워커는
    항상 완전한 데이터로 분석한다. 그래서 실행을 지연시킬 이유도 없다.

    (report, 이벤트 집계, 이번 호출이 리포트를 새로 만들었는지)를 준다. 마지막 값이
    false면 같은 visit_id로 두 번째 이상 호출된 것이라 분석을 다시 돌리지 않는다.
    """
    result = append_batch(visit, event_items) if event_items else dict(EMPTY_EVENT_RESULT)
    _close(visit)
    report, is_new = Report.objects.get_or_create(visit=visit)
    return report, result, is_new


def enqueue(report: Report) -> None:
    """분석을 백그라운드로 넘긴다. 사용자는 여기서 기다리지 않는다."""
    threading.Thread(target=run_analysis, args=(report.pk,), daemon=True).start()


def run_analysis(slug: str) -> None:
    """워커 본체. 예외를 삼키면 사용자가 영원히 pending을 보게 되므로 failed로 남긴다."""
    try:
        report = Report.objects.select_related("visit").get(pk=slug)
        payload, profile = _analyze(report.visit)
        _save(report, payload, profile)
    except Exception as error:  # 스레드에서 죽으면 아무도 모른다. 반드시 상태로 남긴다
        logger.exception("리포트 분석 실패: %s", slug)
        _mark_failed(slug, error)
    finally:
        # 요청 스레드가 아니라 Django가 대신 닫아주지 않는다. 남겨두면 SQLite 커넥션이 샌다.
        connection.close()


def _close(visit: Visit) -> None:
    """관람 종료. visit_end는 프론트가 아니라 서버가 남긴다(퍼널 분모가 두 배가 되지 않게)."""
    if not visit.is_open:
        return  # 멱등 재호출. 이미 닫힌 방문을 다시 닫지 않는다
    record(visit, EventType.VISIT_END)
    visit.ended_at = timezone.now()
    visit.save(update_fields=["ended_at", "updated_at"])


def _analyze(visit: Visit) -> tuple[dict, dict]:
    """①~⑦. 계산 구간에는 쓰기 트랜잭션이 없다 — SQLite가 그만큼 잠기기 때문이다."""
    signals = collect.collect_signals(visit)
    catalog = collect.load_catalog()
    extracted = insight.extract(collect.load_conversation(visit))

    interest = pipeline.compute_interest(signals)
    confidence = pipeline.compute_confidence(signals)
    vector = pipeline.build_vector(interest, {facts.product_id: facts for facts in catalog}, extracted)
    axis_scores = character.score_axes(vector)
    type_code = character.map_type_code(axis_scores)
    scored = pipeline.score_products(vector, catalog, signals.viewed_product_ids)

    payload = report_builder.build_payload(
        signals=signals,
        interest=interest,
        vector=vector,
        confidence=confidence,
        type_code=type_code,
        scored=scored,
        insight=extracted,
    )
    profile = {
        "vector": vector,
        "axis_scores": axis_scores,
        "character_type": type_code,
        "confidence": confidence,
        "insight": extracted.as_dict() if extracted else {},
    }
    return payload, profile


def _save(report: Report, payload: dict, profile: dict) -> None:
    """계산이 전부 끝난 뒤 쓰기 한 번. 트랜잭션을 짧게 유지하는 것이 SQLite 보호책이다."""
    with transaction.atomic():
        TasteProfile.objects.update_or_create(visit=report.visit, defaults=profile)
        report.payload = payload
        report.status = ReportStatus.READY
        report.failure_reason = ""
        report.save(update_fields=["payload", "status", "failure_reason", "updated_at"])


def _mark_failed(slug: str, error: Exception) -> None:
    Report.objects.filter(pk=slug).update(
        status=ReportStatus.FAILED,
        failure_reason=str(error)[:500],
        updated_at=timezone.now(),
    )
