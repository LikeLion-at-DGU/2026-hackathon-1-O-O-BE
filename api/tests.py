"""HTTP 계약 테스트. 실제 URL 라우팅·인증·퍼미션·에러 포맷을 통째로 통과시킨다.

유닛 테스트는 시리얼라이저와 서비스 함수가 맞는지만 본다. 여기서는 "프론트가
실제로 보내는 요청"이 "명세대로의 응답"을 받는지를 본다 — 퍼미션 한 줄이
AllowAny로 바뀌거나 에러 포맷이 달라지는 회귀는 이 층에서만 잡힌다.
"""

import uuid
from datetime import timedelta
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from apps.analysis.models import Report, ReportStatus
from apps.catalog.models import Product, Scene, Store
from apps.events.models import Event, EventType
from apps.lookbook.models import Lookbook
from apps.visits.models import Visit

VALID_PHOTO_KEY = "photos/2026/08/20/0123456789abcdef.jpg"


def event_item(event_type: str, **overrides) -> dict:
    payload = {
        "event_id": str(uuid.uuid4()),
        "event_type": event_type,
        "client_timestamp": "2026-08-20T09:00:00Z",
    }
    payload.update(overrides)
    return payload


class ContractTestBase(TestCase):
    """입장 → 토큰 확보까지를 공통으로 깐다. 매장은 기본 매장 id로 시드해야
    /enter의 get_default_store()가 찾는다."""

    def setUp(self):
        self.client = APIClient()
        store = Store.objects.create(id=settings.DEFAULT_STORE_ID, name="테스트 매장")
        scene = Scene.objects.create(store=store, no=1, name="토트백")
        self.product = Product.objects.create(id="p_101", scene=scene, no=1, name="Milla 토트", price=890000)

    def enter(self, **kwargs) -> dict:
        response = self.client.post("/api/v1/enter", kwargs.pop("body", {}), format="json", **kwargs)
        self.assertEqual(response.status_code, 200)
        return response.json()

    def auth_headers(self, entered: dict) -> dict:
        return {
            "HTTP_X_VISIT_TOKEN": entered["visit_token"],
            "HTTP_X_ANONYMOUS_UUID": entered["anonymous_uuid"],
        }

    def post_events(self, entered: dict, events: list[dict], **header_overrides):
        headers = {**self.auth_headers(entered), **header_overrides}
        return self.client.post(
            "/api/v1/events",
            {"visit_id": entered["visit_id"], "events": events},
            format="json",
            **headers,
        )


class EnterContractTest(ContractTestBase):
    """입장 응답이 깨지면 프론트는 첫 화면에서 죽는다."""

    def test_입장은_토큰과_전시존을_준다(self):
        body = self.enter()
        for key in ("anonymous_uuid", "visit_id", "visit_token", "muse_label", "scenes"):
            self.assertIn(key, body)
        self.assertFalse(body["is_resumed"])
        self.assertEqual(body["scenes"][0]["products"][0]["product_id"], "p_101")

    def test_같은_uuid로_재입장하면_이어받는다(self):
        first = self.enter()
        second = self.enter(HTTP_X_ANONYMOUS_UUID=first["anonymous_uuid"])
        self.assertTrue(second["is_resumed"])
        self.assertEqual(second["visit_id"], first["visit_id"])
        self.assertEqual(second["visit_token"], first["visit_token"])

    def test_force_new는_기존_방문을_닫고_새로_시작한다(self):
        first = self.enter()
        second = self.enter(
            body={"force_new": True},
            HTTP_X_ANONYMOUS_UUID=first["anonymous_uuid"],
        )
        self.assertFalse(second["is_resumed"])
        self.assertNotEqual(second["visit_id"], first["visit_id"])
        self.assertIsNotNone(Visit.objects.get(pk=first["visit_id"]).ended_at)


class VisitTokenContractTest(ContractTestBase):
    """토큰 검문이 풀리면 모든 데이터가 익명이 아니라 무주공산이 된다."""

    def test_토큰_없이_보내면_401이다(self):
        response = self.client.post("/api/v1/events", {"events": []}, format="json")
        self.assertEqual(response.status_code, 401)
        self.assertIn("error", response.json())

    def test_위조_토큰은_401과_에러_코드를_준다(self):
        entered = self.enter()
        response = self.post_events(entered, [], HTTP_X_VISIT_TOKEN="위조된-토큰")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "INVALID_VISIT_TOKEN")

    def test_만료된_토큰은_401이다(self):
        entered = self.enter()
        stale = timezone.now() - settings.VISIT_STALE_AFTER - timedelta(minutes=1)
        Visit.objects.filter(pk=entered["visit_id"]).update(last_seen_at=stale)
        response = self.post_events(entered, [])
        self.assertEqual(response.status_code, 401)


class VisitScopeContractTest(ContractTestBase):
    """토큰이 진실이고 visit_id는 대조용이다. 남의 방문·리포트는 열리면 안 된다."""

    def other_visit(self) -> dict:
        return APIClient().post("/api/v1/enter", {}, format="json").json()

    def test_남의_visit_id로는_이벤트를_못_넣는다(self):
        mine, other = self.enter(), self.other_visit()
        stray = event_item(EventType.PRODUCT_VIEW, product_id="p_101")
        response = self.client.post(
            "/api/v1/events",
            {"visit_id": other["visit_id"], "events": [stray]},
            format="json",
            **self.auth_headers(mine),
        )
        self.assertEqual(response.status_code, 403)

    def test_남의_리포트_후보는_403이다(self):
        mine, other = self.enter(), self.other_visit()
        report = Report.objects.create(
            visit=Visit.objects.get(pk=other["visit_id"]), status=ReportStatus.READY, payload={}
        )
        response = self.client.get(
            f"/api/v1/reports/{report.slug}/lookbook/candidates", **self.auth_headers(mine)
        )
        self.assertEqual(response.status_code, 403)


class EventContractTest(ContractTestBase):
    """이벤트는 append-only 원장이다. 중복·과대값이 들어오면 리포트와 지표가 통째로 오염된다."""

    def test_같은_event_id는_한_번만_저장된다(self):
        entered = self.enter()
        item = event_item(EventType.PRODUCT_VIEW, product_id="p_101")
        first = self.post_events(entered, [item]).json()
        second = self.post_events(entered, [item]).json()
        self.assertEqual(first["accepted"], 1)
        self.assertEqual(second["duplicated"], 1)
        self.assertEqual(Event.objects.filter(event_id=item["event_id"]).count(), 1)

    def test_체류시간은_상한으로_잘린다(self):
        entered = self.enter()
        item = event_item(EventType.PRODUCT_DWELL, product_id="p_101", metadata={"dwell_ms": 9_000_000})
        self.assertEqual(self.post_events(entered, [item]).status_code, 202)
        saved = Event.objects.get(event_id=item["event_id"])
        self.assertEqual(saved.metadata["dwell_ms"], settings.DWELL_MAX_MS)

    def test_종료된_방문에는_화보_이벤트만_쌓인다(self):
        entered = self.enter()
        Visit.objects.filter(pk=entered["visit_id"]).update(ended_at=timezone.now())
        browsing = event_item(EventType.PRODUCT_VIEW, product_id="p_101")
        sharing = event_item(EventType.LOOKBOOK_SHARE)
        result = self.post_events(entered, [browsing, sharing]).json()
        self.assertEqual(result["ignored"], 1)
        self.assertEqual(result["accepted"], 1)


class FinishContractTest(ContractTestBase):
    """종료는 리포트의 문이다. 멱등이 깨지면 더블탭 한 번에 리포트가 두 개 생긴다."""

    def finish(self, entered: dict):
        # 워커 스레드는 띄우지 않는다 — 여기서 보는 것은 HTTP 계약이지 분석이 아니다.
        with patch("apps.analysis.views.services.enqueue"):
            return self.client.post(
                f"/api/v1/visits/{entered['visit_id']}/finish",
                {"events": []},
                format="json",
                **self.auth_headers(entered),
            )

    def test_finish는_두_번_불러도_같은_slug를_준다(self):
        entered = self.enter()
        first, second = self.finish(entered), self.finish(entered)
        self.assertEqual(first.status_code, 202)
        self.assertEqual(first.json()["slug"], second.json()["slug"])
        self.assertEqual(Report.objects.filter(visit_id=entered["visit_id"]).count(), 1)

    def test_리포트는_무인증으로_열리고_처음엔_pending이다(self):
        entered = self.enter()
        slug = self.finish(entered).json()["slug"]
        response = APIClient().get(f"/api/v1/reports/{slug}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], ReportStatus.PENDING)


@override_settings(STORAGE_BACKEND="dev")
class LookbookContractTest(ContractTestBase):
    """화보는 얼굴 사진을 다룬다. 권한과 횟수 제한이 뚫리면 개인정보와 비용이 함께 샌다."""

    def ready_report(self, entered: dict) -> Report:
        return Report.objects.create(
            visit=Visit.objects.get(pk=entered["visit_id"]), status=ReportStatus.READY, payload={}
        )

    def create_body(self) -> dict:
        return {"product_ids": ["p_101"], "photo_key": VALID_PHOTO_KEY, "consent": True}

    def test_남의_리포트로는_화보를_못_만든다(self):
        mine = self.enter()
        other = APIClient().post("/api/v1/enter", {}, format="json").json()
        report = self.ready_report(other)
        response = self.client.post(
            f"/api/v1/reports/{report.slug}/lookbook",
            self.create_body(),
            format="json",
            **self.auth_headers(mine),
        )
        self.assertEqual(response.status_code, 403)

    def test_재생성은_한도를_넘기면_429다(self):
        entered = self.enter()
        report = self.ready_report(entered)
        for attempt in range(1, settings.LOOKBOOK_MAX_ATTEMPT + 1):
            Lookbook.objects.create(report=report, attempt=attempt, photo_key=VALID_PHOTO_KEY)
        response = self.client.post(
            f"/api/v1/reports/{report.slug}/lookbook",
            self.create_body(),
            format="json",
            **self.auth_headers(entered),
        )
        self.assertEqual(response.status_code, 429)


class AdminContractTest(ContractTestBase):
    """브랜드 지표는 B2B 상품이다. 일반 계정에 열리면 그 자체가 유출 사고다."""

    def test_비스태프_계정은_지표를_못_본다(self):
        member = User.objects.create_user(username="member", password="pw")
        token = str(AccessToken.for_user(member))
        response = self.client.get("/api/v1/admin/funnel", HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(response.status_code, 403)
