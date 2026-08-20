"""이벤트 입력 검증과 저장 규칙.

이벤트는 신뢰 경계이자 append-only다. 여기서 막지 못하면 되돌릴 수 없고, 대상이
빠진 이벤트는 저장돼도 분석에서 조용히 사라진다. 문자열 dwell_ms는 저장은 되고
리포트 계산에서 터진다. 그래서 받는 쪽에서 전부 걸러야 한다.
"""

import uuid

from django.conf import settings
from django.test import SimpleTestCase, TestCase
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.catalog.models import Product, Scene, Store
from apps.events.models import EventType
from apps.events.serializers import (
    EVENT_BATCH_HARD_MAX,
    EventItemSerializer,
    validate_batch_size,
)
from apps.events.services import EVENT_BATCH_MAX, append_batch, exposed_scene_ids
from apps.visits import services as visit_services


def raw(event_type: str, **overrides) -> dict:
    """시리얼라이저에 넣기 전의 모양. 클라이언트가 보내는 JSON이다."""
    payload = {
        "event_id": str(uuid.uuid4()),
        "event_type": event_type,
        "client_timestamp": "2026-08-20T09:00:00Z",
    }
    payload.update(overrides)
    return payload


def parsed(event_type: str, **overrides) -> dict:
    """시리얼라이저를 통과한 뒤의 모양. append_batch는 이 형태를 받는다."""
    payload = {
        "event_id": uuid.uuid4(),
        "event_type": event_type,
        "client_timestamp": timezone.now(),
        "scene_id": None,
        "product_id": None,
        "metadata": {},
    }
    payload.update(overrides)
    return payload


class TargetRequiredTest(SimpleTestCase):
    """대상이 없는 이벤트는 저장돼도 분석에서 사라진다. 400으로 알려준다."""

    def test_진열대_이벤트는_scene_id가_필요하다(self):
        serializer = EventItemSerializer(data=raw(EventType.SCENE_DWELL, metadata={"dwell_ms": 5000}))
        self.assertFalse(serializer.is_valid())
        self.assertIn("scene_id", serializer.errors)

    def test_상품_이벤트는_product_id가_필요하다(self):
        serializer = EventItemSerializer(data=raw(EventType.PRODUCT_VIEW))
        self.assertFalse(serializer.is_valid())
        self.assertIn("product_id", serializer.errors)

    def test_핫스팟은_상품이_대상이라_scene_id_없이도_통과한다(self):
        serializer = EventItemSerializer(data=raw(EventType.HOTSPOT_CLICK, product_id="p_101"))
        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_대상이_필요_없는_이벤트도_있다(self):
        serializer = EventItemSerializer(data=raw(EventType.CHATBOT_OPEN))
        self.assertTrue(serializer.is_valid(), serializer.errors)


class DwellValidationTest(SimpleTestCase):
    """체류시간은 관심도 계산에 그대로 들어간다. 숫자가 아니면 여기서 걸러야 한다."""

    def payload(self, dwell) -> dict:
        return raw(EventType.PRODUCT_DWELL, product_id="p_101", metadata={"dwell_ms": dwell})

    def test_정수는_통과한다(self):
        self.assertTrue(EventItemSerializer(data=self.payload(12000)).is_valid())

    def test_문자열은_막는다(self):
        self.assertFalse(EventItemSerializer(data=self.payload("12000")).is_valid())

    def test_음수는_막는다(self):
        self.assertFalse(EventItemSerializer(data=self.payload(-1)).is_valid())

    def test_불리언은_막는다(self):
        # 파이썬에서 True는 int의 하위 타입이라 따로 걸러내지 않으면 1로 통과한다.
        self.assertFalse(EventItemSerializer(data=self.payload(True)).is_valid())

    def test_0은_통과한다(self):
        self.assertTrue(EventItemSerializer(data=self.payload(0)).is_valid())

    def test_dwell_ms가_없으면_검사하지_않는다(self):
        serializer = EventItemSerializer(data=raw(EventType.PRODUCT_VIEW, product_id="p_101"))
        self.assertTrue(serializer.is_valid(), serializer.errors)


class BatchSizeTest(SimpleTestCase):
    """메모리 보호용 절대 상한. 저장 한도(EVENT_BATCH_MAX) 초과와는 다르게 다룬다."""

    def test_상한_이하는_통과한다(self):
        events = [raw(EventType.CHATBOT_OPEN) for _ in range(EVENT_BATCH_HARD_MAX)]
        self.assertEqual(len(validate_batch_size(events)), EVENT_BATCH_HARD_MAX)

    def test_상한을_넘으면_막는다(self):
        events = [raw(EventType.CHATBOT_OPEN) for _ in range(EVENT_BATCH_HARD_MAX + 1)]
        with self.assertRaises(ValidationError):
            validate_batch_size(events)

    def test_저장_한도를_넘어도_400은_아니다(self):
        """/finish에서 400을 내면 버퍼가 조금 많다는 이유로 리포트가 통째로 안 만들어진다."""
        events = [raw(EventType.CHATBOT_OPEN) for _ in range(EVENT_BATCH_MAX + 1)]
        self.assertEqual(len(validate_batch_size(events)), EVENT_BATCH_MAX + 1)


class EventTypeTest(SimpleTestCase):
    def test_찜은_더_이상_받지_않는다(self):
        """기획에서 빠졌고 서버 어디에서도 읽지 않는다. 보내면 400이다."""
        serializer = EventItemSerializer(data=raw("product_save", product_id="p_101"))
        self.assertFalse(serializer.is_valid())
        self.assertIn("event_type", serializer.errors)

    def test_event_id는_UUID여야_한다(self):
        serializer = EventItemSerializer(data=raw(EventType.CHATBOT_OPEN, event_id="not-a-uuid"))
        self.assertFalse(serializer.is_valid())
        self.assertIn("event_id", serializer.errors)


class AppendBatchTest(TestCase):
    """저장 규칙. 한 번 잘못 들어가면 되돌릴 수 없다."""

    def setUp(self):
        store = Store.objects.create(name="테스트 매장")
        Scene.objects.create(id="sc_01", store=store, no=1, name="토트백")
        accessory = Scene.objects.create(id="sc_04", store=store, no=4, name="악세서리")
        Product.objects.create(id="p_401", scene=accessory, no=1, name="참", price=290000)
        visitor, _ = visit_services.resolve_or_issue(None)
        self.visit = visit_services.start(visitor, store)

    def test_같은_배치를_두_번_보내도_한_번만_저장한다(self):
        """멱등이 깨지면 재전송이 수치를 부풀린다. 프론트는 실패 시 그냥 다시 보낸다."""
        batch = [parsed(EventType.PRODUCT_VIEW, product_id="p_401")]

        first = append_batch(self.visit, batch)
        second = append_batch(self.visit, batch)

        self.assertEqual(first["accepted"], 1)
        self.assertEqual(second["accepted"], 0)
        self.assertEqual(second["duplicated"], 1)
        self.assertEqual(self.visit.events.filter(event_type=EventType.PRODUCT_VIEW).count(), 1)

    def test_한_배치_안의_중복은_하나만_남긴다(self):
        event = parsed(EventType.PRODUCT_VIEW, product_id="p_401")
        self.assertEqual(append_batch(self.visit, [event, dict(event)])["accepted"], 1)

    def test_없는_상품을_가리키면_거부한다(self):
        """조용히 버리면 분석 수치가 눈에 안 보이게 틀어진다."""
        with self.assertRaises(ValidationError):
            append_batch(self.visit, [parsed(EventType.PRODUCT_VIEW, product_id="p_999")])

    def test_체류시간_상한을_넘으면_자른다(self):
        """탭을 백그라운드에 두면 30분이 찍힌다. 검증 없이 믿으면 프로필이 한 상품에 끌려간다."""
        over = settings.DWELL_MAX_MS + 60_000
        append_batch(
            self.visit,
            [parsed(EventType.PRODUCT_DWELL, product_id="p_401", metadata={"dwell_ms": over})],
        )
        event = self.visit.events.get(event_type=EventType.PRODUCT_DWELL)
        self.assertEqual(event.metadata["dwell_ms"], settings.DWELL_MAX_MS)

    def test_서버가_만드는_타입은_받지_않는다(self):
        """프론트가 visit_start를 같이 보내면 퍼널의 분모가 두 배가 된다."""
        before = self.visit.events.filter(event_type=EventType.VISIT_START).count()
        result = append_batch(self.visit, [parsed(EventType.VISIT_START)])

        self.assertEqual(result["accepted"], 0)
        self.assertEqual(result["ignored"], 1)
        self.assertEqual(self.visit.events.filter(event_type=EventType.VISIT_START).count(), before)

    def test_종료된_관람에는_화보_이벤트만_받는다(self):
        """리포트는 /finish 시점에 박제된다. 뒤늦은 상품 조회는 반영될 수 없다."""
        self.visit.ended_at = timezone.now()
        self.visit.save(update_fields=["ended_at"])

        rejected = append_batch(self.visit, [parsed(EventType.PRODUCT_VIEW, product_id="p_401")])
        accepted = append_batch(self.visit, [parsed(EventType.PHOTO_CAPTURE)])

        self.assertEqual(rejected["ignored"], 1)
        self.assertEqual(accepted["accepted"], 1)

    def test_핫스팟의_진열대를_상품에서_역추적한다(self):
        """프론트가 scene_id를 못 구하면 sc_01을 넣는다.

        그러면 4번 진열대를 눌러도 1번으로 기록된다. 존재하는 id라 에러도 안 나고
        조용히 틀리므로, 클라이언트가 보낸 값을 서버가 덮어쓴다.
        """
        append_batch(self.visit, [parsed(EventType.HOTSPOT_CLICK, product_id="p_401", scene_id="sc_01")])
        self.assertEqual(self.visit.events.get(event_type=EventType.HOTSPOT_CLICK).scene_id, "sc_04")

    def test_상품_이벤트만_있어도_노출된_진열대를_안다(self):
        """프론트가 scene_view를 보내지 않아 회피 트리거가 죽어 있었다."""
        append_batch(self.visit, [parsed(EventType.PRODUCT_VIEW, product_id="p_401")])
        self.assertEqual(exposed_scene_ids(self.visit), {"sc_04"})

    def test_저장_한도를_넘으면_초과분을_rejected로_알려준다(self):
        batch = [parsed(EventType.CHATBOT_OPEN) for _ in range(EVENT_BATCH_MAX + 3)]
        result = append_batch(self.visit, batch)

        self.assertEqual(result["accepted"], EVENT_BATCH_MAX)
        self.assertEqual(result["rejected"], 3)
