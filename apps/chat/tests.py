"""챗봇의 순수 함수 테스트. DB도 LLM도 붙이지 않는다.

여기 모인 것들은 **틀려도 에러가 안 나는** 로직이다. 조사가 틀리면 문장이 어색할
뿐 예외가 안 나고, 축 추출이 엉뚱한 축을 짚어도 추천이 그럴듯하게 나오고, LLM이
없는 상품을 지어내도 200으로 응답한다. 화면에서 눈치채기까지 오래 걸리므로
여기서 잡는다.
"""

import uuid
from datetime import timedelta
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from apps.analysis.recommend import Suggestion
from apps.analysis.taste import profile_of
from apps.catalog.models import Color, Material, Mood, Product, Scene, Store, UseCase
from apps.chat import answers, taste_map, triggers
from apps.chat.services import _absorb
from apps.chat.wording import say, with_object, with_subject
from apps.events.models import Event, EventType
from apps.visits import services as visit_services
from apps.visits.models import Visit
from common.llm import LLMUnavailable


def make_product(name: str, color: str = Color.BLACK, scene_no: int = 1, no: int = 1) -> Product:
    """저장하지 않는 인스턴스. 표시용 필드만 채우면 되므로 DB가 필요 없다."""
    product = Product(id=f"p_{scene_no}{no:02d}", name=name, no=no, color=color)
    product.scene = Scene(id=f"sc_{scene_no:02d}", no=scene_no, name="토트백")
    return product


def suggest(product: Product) -> Suggestion:
    return Suggestion(product=product, score=0.9, reason="비슷한 결")


class ParticleTest(SimpleTestCase):
    """조사는 상품명 끝 글자에 달렸다. 60개 중 37개가 받침 없이 끝난다."""

    def test_받침이_있으면_을_없으면_를(self):
        self.assertEqual(with_object("백팩"), "백팩을")
        self.assertEqual(with_object("토트"), "토트를")

    def test_받침이_있으면_이_없으면_가(self):
        self.assertEqual(with_subject("색"), "색이")
        self.assertEqual(with_subject("소재"), "소재가")

    def test_한글이_아닌_글자로_끝나면_받침_없음으로_본다(self):
        # "ECONYL®과"처럼 기호로 끝나는 이름이 실제로 있다. 둘 중 하나는 골라야 한다.
        self.assertEqual(with_object("ECONYL®"), "ECONYL®를")

    def test_손님용_표현이_없는_값은_그대로_내보낸다(self):
        # 조용히 비우면 문구에서 값이 사라져 누락을 못 본다.
        self.assertEqual(say("존재하지_않는_값"), "존재하지_않는_값")


class ExtractTest(SimpleTestCase):
    """사전 기반 축 추출. 부정 절을 잘못 끊으면 선호와 비선호가 통째로 뒤집힌다."""

    def test_색_이름은_사전이_바로_잡는다(self):
        preferred, rejected = taste_map.extract("검정색이 좋아요")
        self.assertEqual(preferred, {"color": [Color.BLACK]})
        self.assertEqual(rejected, {})

    def test_말고는_비선호로_넘어간다(self):
        preferred, rejected = taste_map.extract("검은색 말고요")
        self.assertEqual(preferred, {})
        self.assertEqual(rejected, {"color": [Color.BLACK]})

    def test_한_절이_좋고_다른_절이_싫으면_따로_잡는다(self):
        # "고 "를 못 끊으면 문장 전체가 부정으로 먹혀 검정까지 비선호가 된다.
        preferred, rejected = taste_map.extract("검정은 좋고 빨강은 싫어요")
        self.assertEqual(preferred, {"color": [Color.BLACK]})
        self.assertEqual(rejected, {"color": [Color.RED]})

    def test_한_축에_비선호_값이_여럿_올_수_있다(self):
        _, rejected = taste_map.extract("빨강도 핑크도 싫어요")
        self.assertEqual(set(rejected["color"]), {Color.RED, Color.PINK})

    def test_무드_형용사는_사전이_잡지_않는다(self):
        # 어느 축인지는 뒤에 붙는 명사가 정한다("차분한 색"은 color, "차분한 결"은 mood).
        # 사전은 단어만 보므로 구분할 수 없어 LLM에 넘긴다.
        preferred, rejected = taste_map.extract("차분한 색이 좋아요")
        self.assertEqual((preferred, rejected), ({}, {}))

    def test_한_표현이_여러_축을_짚을_수_있다(self):
        preferred, _ = taste_map.extract("오래 쓸 가방이요")
        self.assertEqual(preferred["material"], [Material.GRAINED_LEATHER])
        self.assertIn("silhouette", preferred)

    def test_재고가_없는_축_값으로는_보내지_않는다(self):
        # use_case=travel 상품이 없다. lock되면 추천 점수가 전부 0이 된다.
        preferred, _ = taste_map.extract("여행 갈 때 쓸 거요")
        self.assertNotIn(UseCase.TRAVEL, preferred.get("use_case", []))


class InventedTest(SimpleTestCase):
    """추천 문장 검증. 프롬프트로 지시해도 확률적으로 새므로 서버가 대조한다."""

    def setUp(self):
        self.spoken = [suggest(make_product("Milla 그레인 가죽 토트", Color.COGNAC, scene_no=1))]

    def test_목록에_없는_색을_말하면_걸러낸다(self):
        message = "1번 진열대의 Milla 그레인 가죽 토트가 코냑과 베이지로 있어요."
        self.assertTrue(answers._invented(message, self.spoken))

    def test_목록에_없는_진열대를_말하면_걸러낸다(self):
        message = "7번 진열대의 Milla 그레인 가죽 토트를 추천드려요."
        self.assertTrue(answers._invented(message, self.spoken))

    def test_이름이_훼손되면_걸러낸다(self):
        # 끝의 한 낱말이 종류를 가른다 — "백팩 참"에서 "참"이 빠지면 액세서리가 가방이 된다.
        message = "1번 진열대의 Milla 토트를 추천드려요."
        self.assertTrue(answers._invented(message, self.spoken))

    def test_목록대로_말하면_통과시킨다(self):
        message = "1번 진열대의 Milla 그레인 가죽 토트를 추천드려요."
        self.assertFalse(answers._invented(message, self.spoken))


class SpeakFallbackTest(SimpleTestCase):
    """문장 생성이 실패해도 답은 나가야 한다. 버튼을 눌렀는데 아무 반응이 없으면 안 된다."""

    LEAD = "그럼 이런 것도 보실래요?"

    def setUp(self):
        self.spoken = [suggest(make_product("Milla 그레인 가죽 토트", Color.COGNAC))]

    def test_LLM이_죽으면_기존_문구로_내보낸다(self):
        with patch("apps.chat.answers.complete_json", side_effect=LLMUnavailable()):
            self.assertEqual(answers._speak(self.LEAD, self.spoken), self.LEAD)

    def test_빈_응답이면_기존_문구로_내보낸다(self):
        with patch("apps.chat.answers.complete_json", return_value={"message": "   "}):
            self.assertEqual(answers._speak(self.LEAD, self.spoken), self.LEAD)

    def test_지어낸_문장이면_기존_문구로_내보낸다(self):
        invented = {"message": "7번 진열대의 Milla 그레인 가죽 토트가 베이지로 있어요."}
        with patch("apps.chat.answers.complete_json", return_value=invented):
            self.assertEqual(answers._speak(self.LEAD, self.spoken), self.LEAD)

    def test_정상_문장은_그대로_쓴다(self):
        good = {"message": "1번 진열대의 Milla 그레인 가죽 토트를 추천드려요."}
        with patch("apps.chat.answers.complete_json", return_value=good):
            self.assertEqual(answers._speak(self.LEAD, self.spoken), good["message"])

    def test_말할_상품이_둘까지만_넘어간다(self):
        """셋을 나열하면 문장이 목록이 된다. 프롬프트가 아니라 코드가 자른다."""
        products = [make_product(f"상품 {i}", no=i) for i in range(1, 4)]
        captured = {}

        def spy(system, user, schema=None):
            captured["user"] = user
            return {"message": "1번 진열대의 상품 1을 추천드려요."}

        with patch("apps.chat.answers.complete_json", side_effect=spy):
            answers._speak(self.LEAD, [suggest(p) for p in products])
        self.assertNotIn("상품 3", captured["user"])


class TriggerTestBase(TestCase):
    """관람 중인 손님을 만든다. 워밍업을 넘기려면 입장 시각을 되돌려야 한다."""

    def setUp(self):
        self.store = Store.objects.create(name="테스트 매장")
        self.scene = Scene.objects.create(id="sc_01", store=self.store, no=1, name="토트백")
        self.other = Scene.objects.create(id="sc_02", store=self.store, no=2, name="백팩")
        visitor, _ = visit_services.resolve_or_issue(None)
        self.visit = visit_services.start(visitor, self.store)
        Visit.objects.filter(pk=self.visit.pk).update(started_at=timezone.now() - timedelta(minutes=10))
        self.visit.refresh_from_db()

    def product(self, no: int, mood: str = Mood.MINIMAL, scene: Scene | None = None) -> Product:
        scene = scene or self.scene
        return Product.objects.create(
            id=f"p_{scene.no}{no:02d}",
            scene=scene,
            no=no,
            name=f"상품 {scene.no}-{no}",
            price=890000,
            mood=mood,
        )

    def view(self, product: Product, dwell_ms: int = 8_000, times: int = 1) -> None:
        """조회 + 체류를 함께 남긴다. 트리거는 '스친 것'과 '본 것'을 가른다."""
        for _ in range(times):
            Event.objects.create(
                event_id=uuid.uuid4(),
                visit=self.visit,
                event_type=EventType.PRODUCT_VIEW,
                product=product,
                scene=product.scene,
                client_timestamp=timezone.now(),
            )
        Event.objects.create(
            event_id=uuid.uuid4(),
            visit=self.visit,
            event_type=EventType.PRODUCT_DWELL,
            product=product,
            scene=product.scene,
            client_timestamp=timezone.now(),
            metadata={"dwell_ms": dwell_ms},
        )

    def vector(self, **fields) -> dict:
        profile = profile_of(self.visit)
        profile.vector = {**profile.vector, **fields}
        profile.save()
        return profile.vector


class TriggerGateTest(TriggerTestBase):
    """묻는 것은 비용이다. 문지기가 뚫리면 손님이 질문 세례를 받는다."""

    def test_상품을_적게_봤으면_묻지_않는다(self):
        self.view(self.product(1), dwell_ms=35_000)
        self.assertIsNone(triggers.evaluate(self.visit))

    def test_입장_직후에는_묻지_않는다(self):
        """워밍업 60초. 들어오자마자 질문하면 관찰이 아니라 설문이 된다."""
        Visit.objects.filter(pk=self.visit.pk).update(started_at=timezone.now())
        self.visit.refresh_from_db()
        for no in (1, 2, 3):
            self.view(self.product(no), dwell_ms=35_000)
        self.assertIsNone(triggers.evaluate(self.visit))

    def test_예산을_다_쓰면_묻지_않는다(self):
        for no in (1, 2, 3):
            self.view(self.product(no), dwell_ms=35_000)
        self.vector(confirm_count=triggers.CONFIRM_BUDGET)
        self.assertIsNone(triggers.evaluate(self.visit))

    def test_쿨다운_안에서는_묻지_않는다(self):
        """확인 사이에 상품을 두 개는 더 봐야 한다."""
        for no in (1, 2, 3):
            self.view(self.product(no), dwell_ms=35_000)
        self.vector(asked_at_views=3)
        self.assertIsNone(triggers.evaluate(self.visit))

    def test_그냥_둘러보겠다고_하면_그_방문엔_더_묻지_않는다(self):
        for no in (1, 2, 3):
            self.view(self.product(no), dwell_ms=35_000)
        self.vector(browse_only=True)
        self.assertIsNone(triggers.evaluate(self.visit))


class TriggerKindTest(TriggerTestBase):
    """어느 가설을 던지는가. 순서가 바뀌면 뒤쪽 트리거가 도달 불가가 된다."""

    def test_오래_본_상품을_짚는다(self):
        for no in (1, 2, 3):
            self.view(self.product(no), dwell_ms=8_000)
        self.view(self.product(4), dwell_ms=triggers.CONFIRM_DWELL_MS + 1_000)

        hypothesis = triggers.evaluate(self.visit)
        self.assertEqual(hypothesis.kind, "product_confirm")

    def test_왕복_조회는_대비_2택을_던진다(self):
        first, second = self.product(1), self.product(2)
        self.view(first)
        self.view(second)
        self.view(first)

        hypothesis = triggers.evaluate(self.visit)
        self.assertEqual(hypothesis.kind, "contrast")
        self.assertEqual(len(hypothesis.options), 2)

    def test_중복_조회가_끼어도_왕복을_알아본다(self):
        """프론트가 재마운트로 product_view를 두 번 보내면 [A,A,B,B,A,A]가 된다.
        연속 중복을 압축하지 않으면 왕복 판정이 영원히 성립하지 않는다."""
        first, second = self.product(1), self.product(2)
        for product in (first, first, second, second, first, first):
            self.view(product)

        self.assertEqual(triggers.evaluate(self.visit).kind, "contrast")

    def test_왕복_신호는_조회_한_건_뒤에도_남는다(self):
        """왕복이 성립한 순간 게이트에 막혀도, 창 안에 있는 동안은 소비할 수 있어야
        한다. 마지막 3건만 보면 다음 조회 한 번에 신호가 영영 사라진다."""
        first, second = self.product(1), self.product(2)
        self.view(first)
        self.view(second)
        self.view(first)
        self.view(self.product(3))

        self.assertEqual(triggers.evaluate(self.visit).kind, "contrast")

    def test_대비가_상품_확인보다_먼저다(self):
        """왕복 조회는 재조회의 특수한 경우다.

        1군(상품 확인)을 앞에 두면 항상 1군이 먹고 2군은 영원히 발동하지 않는다.
        """
        first, second = self.product(1), self.product(2)
        self.view(first, dwell_ms=triggers.CONFIRM_DWELL_MS + 1_000)
        self.view(second)
        self.view(first)

        self.assertEqual(triggers.evaluate(self.visit).kind, "contrast")

    def test_훑고_지나가면_방향을_묻는다(self):
        """체류 5초를 한 번도 못 넘긴 손님. 아무 신호 없이 리포트가 나가는 걸 막는다."""
        for no in range(1, triggers.SKIM_VIEWS + 1):
            self.view(self.product(no), dwell_ms=1_000)

        hypothesis = triggers.evaluate(self.visit)
        self.assertEqual(hypothesis.kind, "quick_browse")
        self.assertIn("browse_only", [option.get("option") for option in hypothesis.options])


class ShiftTriggerTest(TriggerTestBase):
    """확정한 축의 반대 진영을 보고 있을 때 다시 묻는다. 같은 축 1회 제한의 유일한 예외다."""

    def setUp(self):
        super().setUp()
        self.opposite = [self.product(no, mood=Mood.Y2K_STREET, scene=self.other) for no in (1, 2, 3)]
        for product in self.opposite:
            self.view(product)

    def test_확인한_상품이_없으면_묻지_않는다(self):
        """원래 조건은 '찜'이었다. 찜이 빠지면서 영원히 거짓이 되어 한 번도 발동하지 않았다."""
        self.vector(locks={"mood": Mood.MINIMAL})
        self.assertIsNone(triggers._shift(self.visit, profile_of(self.visit).vector))

    def test_반대_진영을_확인했으면_다시_묻는다(self):
        self.vector(locks={"mood": Mood.MINIMAL}, confirmed=[self.opposite[0].id])

        hypothesis = triggers._shift(self.visit, profile_of(self.visit).vector)
        self.assertEqual(hypothesis.kind, "shift")
        self.assertEqual(hypothesis.axis, "mood")

    def test_한_방문에_한_번만_묻는다(self):
        self.vector(locks={"mood": Mood.MINIMAL}, confirmed=[self.opposite[0].id], shift_asked=True)
        self.assertIsNone(triggers._shift(self.visit, profile_of(self.visit).vector))


class AbsorbTest(TriggerTestBase):
    """발화에서 뽑은 축을 좌표에 얹는다. 손님이 직접 말한 것은 lock으로 취급한다."""

    def test_선호는_spoken에_들어간다(self):
        extracted = _absorb(self.visit, "검정색이 좋아요")
        self.assertEqual(profile_of(self.visit).vector["spoken"], {"color": Color.BLACK})
        self.assertTrue(extracted["needs_confirm"])

    def test_부정은_회피율로_들어간다(self):
        _absorb(self.visit, "빨강은 싫어요")
        avoided = profile_of(self.visit).vector["avoided"]
        self.assertEqual(avoided["color"][Color.RED], answers.AVOID_RATE)

    def test_사전이_잡으면_LLM을_부르지_않는다(self):
        """흔한 말은 1차에서 끝나야 한다. 매 발화마다 호출이 붙으면 답변이 느려진다."""
        with patch("apps.chat.taste_map.llm_extract") as llm:
            _absorb(self.visit, "검정색이 좋아요")
        llm.assert_not_called()

    def test_아무것도_못_읽으면_좌표를_건드리지_않는다(self):
        with patch("apps.chat.taste_map.llm_extract", return_value=({}, {})):
            extracted = _absorb(self.visit, "음 글쎄요")
        self.assertEqual(extracted, {"axes": {}, "needs_confirm": False})
