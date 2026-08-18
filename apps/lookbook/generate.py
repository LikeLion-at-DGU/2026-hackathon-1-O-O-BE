"""화보 생성 접수. 큐에 넣고 즉시 202를 돌려준다 — `/finish`와 같은 패턴이다.

명세의 서버 처리 순서 ①~⑩을 그대로 따른다. 검증을 먼저 다 끝내고 마지막에
insert + 큐 적재를 한 트랜잭션으로 묶는다.
"""

import logging

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Max
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.analysis.models import Report, ReportStatus
from apps.catalog.models import Product
from apps.lookbook import composition as composition_picker
from apps.lookbook import jobs, storage
from apps.lookbook.errors import RegenerationLimit, ReportPending
from apps.lookbook.models import Composition, Lookbook

logger = logging.getLogger(__name__)

MOOD_KEY = "mood"
SEED_META_KEY = "_meta"


def accept(report: Report, visit, payload: dict) -> Lookbook:
    """①~⑩. 통과하면 큐에 올라간 Lookbook을 준다."""
    _assert_owns(report, visit)  # ①
    _assert_ready(report)  # ②
    products = _resolve_products(payload["product_ids"])  # ③④
    _assert_consent(payload["consent"])  # ⑤
    _verify_uploads(payload)  # ⑥⑦

    return _create(report, visit, payload, products)  # ⑧⑨⑩


def _assert_owns(report: Report, visit) -> None:
    if report.visit_id != visit.id:
        raise PermissionDenied("이 리포트의 방문이 아닙니다.")


def _assert_ready(report: Report) -> None:
    if report.status != ReportStatus.READY:
        raise ReportPending()


def _resolve_products(product_ids: list[str]) -> list[Product]:
    if len(product_ids) > settings.LOOKBOOK_MAX_SELECT:
        raise ValidationError({"product_ids": ["too_many_products"]})

    products = list(Product.objects.filter(id__in=product_ids))
    if len(products) != len(set(product_ids)):
        raise ValidationError({"product_ids": ["unknown_product"]})
    return products


def _assert_consent(consent: bool) -> None:
    """얼굴 사진을 다루므로 동의 없이는 시작하지 않는다."""
    if not consent:
        raise ValidationError({"consent": ["consent_required"]})


def _verify_uploads(payload: dict) -> None:
    """선언한 content_type이 아니라 실제 바이트를 본다."""
    for field in ("photo_key", "mask_key"):
        key = payload.get(field)
        if not key:
            continue  # mask는 선택이다. 없으면 체형 보존이 약해질 뿐 생성은 된다
        try:
            storage.verify_upload(key)
        except storage.UploadNotFound:
            raise ValidationError({field: ["upload_not_found"]}) from None
        except storage.NotAnImage:
            raise ValidationError({field: ["not_an_image"]}) from None


def _create(report: Report, visit, payload: dict, products: list[Product]) -> Lookbook:
    """attempt 계산부터 큐 적재까지. 연타로 같은 attempt가 두 번 나가면 생성 비용이 두 배다."""
    with transaction.atomic():
        locked = Report.objects.select_for_update().get(pk=report.pk)
        attempt = (locked.lookbooks.aggregate(top=Max("attempt"))["top"] or 0) + 1
        if attempt > settings.LOOKBOOK_MAX_ATTEMPT:
            raise RegenerationLimit()

        seed = composition_picker.seed_for(visit.id, attempt)
        chosen = composition_picker.choose(
            list(Composition.objects.all()),
            payload.get("photo_meta", {}).get("face_ratio"),
            seed,
            used_codes=tuple(locked.lookbooks.values_list("composition_id", flat=True)),
        )

        try:
            lookbook = Lookbook.objects.create(
                report=locked,
                attempt=attempt,
                product_ids=[product.id for product in products],
                photo_key=payload["photo_key"],
                mask_key=payload.get("mask_key") or "",
                composition=chosen,
                mood_payload=_mood_payload(locked, seed),
            )
        except IntegrityError:
            # UniqueConstraint(report, attempt)에 걸렸다. 동시 요청이라 500이 아니라 충돌이다.
            raise RegenerationLimit("이미 같은 회차가 생성 중입니다.") from None

    jobs.write(
        jobs.JobState(
            job_id=lookbook.job_id,
            share_slug=lookbook.share_slug,
            attempt=lookbook.attempt,
            status=jobs.STATUS_QUEUED,
        )
    )
    return lookbook


def _mood_payload(report: Report, seed: int) -> dict:
    """리포트에 박제된 무드를 그대로 복사하고 seed를 함께 남긴다.

    무드는 `/finish` 워커가 이미 정했다. 생성 시점에 다시 계산하면 같은 리포트인데
    화보마다 톤이 달라진다. 랜덤은 구도 선택에만 들어간다.
    """
    mood = report.payload.get(MOOD_KEY, {}) if isinstance(report.payload, dict) else {}
    return {**mood, SEED_META_KEY: {"seed": seed}}


def remaining_regenerations(attempt: int) -> int:
    return max(0, settings.LOOKBOOK_MAX_ATTEMPT - attempt)
