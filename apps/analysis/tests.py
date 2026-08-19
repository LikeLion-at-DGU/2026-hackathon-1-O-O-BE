"""파이프라인 순수 함수 테스트. 이 프로젝트의 유일한 테스트다.

여기만 테스트하는 이유는, 나머지가 깨지면 화면에서 바로 보이지만 스코어링은
**틀려도 그럴듯한 값이 나와서** 아무도 눈치채지 못하기 때문이다.
"""

from django.test import SimpleTestCase

from apps.analysis import pipeline, scoring
from apps.analysis.insight import Insight
from apps.analysis.signals import ProductFacts, ProductSignal, VisitSignals

AXES = {
    "category": "backpack",
    "color": "black",
    "material": "smooth_leather",
    "pattern": "solid",
    "silhouette": "structured",
    "mood": "minimal",
    "price_band": "mid",
    "use_case": "daily",
}


def make_facts(product_id: str, **overrides) -> ProductFacts:
    axes = {**AXES, **overrides.pop("axes", {})}
    return ProductFacts(
        product_id=product_id,
        name=f"상품 {product_id}",
        thumbnail=None,
        price=890000,
        external_url="https://example.com",
        scene_no=1,
        product_no=1,
        is_new=overrides.pop("is_new", False),
        popularity=overrides.pop("popularity", 0.0),
        axes=axes,
    )


class InterestTest(SimpleTestCase):
    def test_한_상품만_반복_조회해도_다른_상품을_지우지_않는다(self):
        signals = VisitSignals(
            products=(
                ProductSignal("p_1", views=30),
                ProductSignal("p_2", views=3),
            )
        )

        interest = pipeline.compute_interest(signals)

        self.assertEqual(interest["p_1"], 1.0)
        # log 가중이라 10배 조회가 10배 관심이 되지 않는다
        self.assertGreater(interest["p_2"], 0.3)

    def test_신호가_없으면_빈_결과다(self):
        self.assertEqual(pipeline.compute_interest(VisitSignals()), {})


class ConfidenceTest(SimpleTestCase):
    def test_이벤트가_없으면_0이다(self):
        self.assertEqual(pipeline.compute_confidence(VisitSignals()), 0.0)

    def test_신호가_충분하면_1로_수렴한다(self):
        signals = VisitSignals(
            products=tuple(
                ProductSignal(f"p_{index}", views=2, dwell_ms=60_000) for index in range(8)
            ),
            questions=3,
        )

        self.assertEqual(pipeline.compute_confidence(signals), 1.0)

    def test_조회만_있으면_탐색_중_기준을_넘지_못한다(self):
        signals = VisitSignals(products=(ProductSignal("p_1", views=1),))

        self.assertLess(pipeline.compute_confidence(signals), scoring.CONFIDENCE_EXPLORING)


class VectorTest(SimpleTestCase):
    def test_상품_선호가_속성_선호로_바뀐다(self):
        facts = make_facts("p_1")

        vector = pipeline.build_vector({"p_1": 1.0}, {"p_1": facts}, None)

        self.assertEqual(vector["color:black"], 1.0)
        self.assertEqual(vector["material:smooth_leather"], 1.0)

    def test_대화의_비선호는_감점된다(self):
        facts = make_facts("p_1")
        insight = Insight(avoids=(("color", "black"),))

        vector = pipeline.build_vector({"p_1": 1.0}, {"p_1": facts}, insight)

        self.assertLess(vector["color:black"], vector["material:smooth_leather"])


class ScoringTest(SimpleTestCase):
    def test_취향에_맞는_상품이_위로_온다(self):
        catalog = (
            make_facts("p_match"),
            make_facts("p_other", axes={"color": "pink", "material": "nylon", "mood": "y2k_street"}),
        )
        vector = pipeline.build_vector({"p_match": 1.0}, {"p_match": catalog[0]}, None)

        scored = pipeline.score_products(vector, catalog, frozenset())

        self.assertEqual(scored[0].facts.product_id, "p_match")

    def test_안_본_상품에만_발견_가산이_붙는다(self):
        catalog = (make_facts("p_1"),)

        viewed = pipeline.score_products({}, catalog, frozenset({"p_1"}))[0]
        unseen = pipeline.score_products({}, catalog, frozenset())[0]

        self.assertAlmostEqual(unseen.score - viewed.score, scoring.DISCOVERY_BONUS, places=4)

    def test_이벤트가_전혀_없어도_추천이_나온다(self):
        catalog = (make_facts("p_1"), make_facts("p_2"))

        scored = pipeline.score_products({}, catalog, frozenset())

        self.assertEqual(len(scored), 2)
