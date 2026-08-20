"""브랜드 지표. 손님 API와 인증 방식이 다르므로 문이 제대로 잠겼는지부터 본다.

집계는 틀려도 에러가 안 난다 — 그럴듯한 숫자가 나오고, 그 숫자로 진열과 직원 배치를
정하게 된다. 그래서 전환율의 분모와 중복 제거를 여기서 못 박는다.
"""

import uuid

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.analysis.models import Report, ReportStatus
from apps.catalog.models import Product, Scene, Store
from apps.dashboard import services
from apps.events.models import Event, EventType
from apps.visits import services as visit_services


class DashboardTestBase(TestCase):
    def setUp(self):
        self.store = Store.objects.create(name="테스트 매장")
        scene = Scene.objects.create(id="sc_01", store=self.store, no=1, name="토트백")
        self.product = Product.objects.create(id="p_101", scene=scene, no=1, name="Milla 토트", price=890000)
        self.client = APIClient()

    def make_visit(self):
        visitor, _ = visit_services.resolve_or_issue(None)
        return visit_services.start(visitor, self.store)

    def add_event(self, visit, event_type, **fields):
        Event.objects.create(
            event_id=uuid.uuid4(),
            visit=visit,
            event_type=event_type,
            client_timestamp=timezone.now(),
            **fields,
        )


class AdminAccessTest(DashboardTestBase):
    """지표는 브랜드만 본다. 손님 토큰으로는 열리지 않아야 한다."""

    def test_인증_없이는_막는다(self):
        self.assertEqual(self.client.get("/api/v1/admin/funnel").status_code, 401)
        self.assertEqual(self.client.get("/api/v1/admin/products").status_code, 401)

    def test_staff가_아니면_토큰을_주지_않는다(self):
        User.objects.create_user("guest@mcm.test", password="pw12345!", is_staff=False)
        response = self.client.post(
            "/api/v1/admin/auth",
            {"email": "guest@mcm.test", "password": "pw12345!"},
            format="json",
        )
        self.assertEqual(response.status_code, 401)

    def test_staff는_토큰으로_지표를_본다(self):
        User.objects.create_user("brand@mcm.test", password="pw12345!", is_staff=True)
        token = self.client.post(
            "/api/v1/admin/auth",
            {"email": "brand@mcm.test", "password": "pw12345!"},
            format="json",
        ).json()["access_token"]

        response = self.client.get("/api/v1/admin/funnel", HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(response.status_code, 200)


class FunnelTest(DashboardTestBase):
    def test_전환율의_분모는_입장이다(self):
        """직전 단계 대비로 보면 뒤로 갈수록 좋아 보여서 이탈 지점이 안 보인다."""
        for _ in range(4):
            self.make_visit()
        self.add_event(self.make_visit(), EventType.PRODUCT_VIEW, product=self.product)

        stages = {stage["key"]: stage for stage in services.funnel(self.store.id)["stages"]}
        self.assertEqual(stages["entered"]["visits"], 5)
        self.assertEqual(stages["viewed_product"]["visits"], 1)
        self.assertEqual(stages["viewed_product"]["rate"], 0.2)

    def test_한_방문이_여러_번_봐도_한_명으로_센다(self):
        visit = self.make_visit()
        for _ in range(3):
            self.add_event(visit, EventType.PRODUCT_VIEW, product=self.product)

        stages = {stage["key"]: stage for stage in services.funnel(self.store.id)["stages"]}
        self.assertEqual(stages["viewed_product"]["visits"], 1)

    def test_리포트는_완료된_것만_센다(self):
        Report.objects.create(visit=self.make_visit(), status=ReportStatus.PENDING)
        Report.objects.create(visit=self.make_visit(), status=ReportStatus.READY)

        stages = {stage["key"]: stage for stage in services.funnel(self.store.id)["stages"]}
        self.assertEqual(stages["got_report"]["visits"], 1)

    def test_방문이_없어도_0으로_나눈다고_죽지_않는다(self):
        funnel = services.funnel(self.store.id)
        self.assertEqual(funnel["stages"][0]["rate"], 0.0)


class ProductStatTest(DashboardTestBase):
    def test_체류가_긴_상품이_먼저_온다(self):
        other = Product.objects.create(
            id="p_102", scene=self.product.scene, no=2, name="Aren 토트", price=790000
        )
        visit = self.make_visit()
        self.add_event(visit, EventType.PRODUCT_DWELL, product=self.product, metadata={"dwell_ms": 5_000})
        self.add_event(visit, EventType.PRODUCT_DWELL, product=other, metadata={"dwell_ms": 40_000})

        stats = services.product_stats(self.store.id)
        self.assertEqual([row["product_id"] for row in stats], ["p_102", "p_101"])

    def test_추천_클릭률은_노출_대비다(self):
        visit = self.make_visit()
        for _ in range(4):
            self.add_event(visit, EventType.RECOMMENDATION_IMPRESSION, product=self.product)
        self.add_event(visit, EventType.RECOMMENDATION_CLICK, product=self.product)

        row = next(r for r in services.product_stats(self.store.id) if r["product_id"] == "p_101")
        self.assertEqual(row["click_rate"], 0.25)

    def test_노출이_0이면_클릭률도_0이다(self):
        visit = self.make_visit()
        self.add_event(visit, EventType.PRODUCT_VIEW, product=self.product)

        row = next(r for r in services.product_stats(self.store.id) if r["product_id"] == "p_101")
        self.assertEqual(row["click_rate"], 0.0)

    def test_망가진_체류값은_세지_않는다(self):
        """문자열 dwell_ms는 시리얼라이저가 막지만, 과거 데이터가 남아 있을 수 있다."""
        visit = self.make_visit()
        self.add_event(visit, EventType.PRODUCT_DWELL, product=self.product, metadata={"dwell_ms": "40000"})

        row = next(r for r in services.product_stats(self.store.id) if r["product_id"] == "p_101")
        self.assertEqual(row["dwell_ms"], 0)
