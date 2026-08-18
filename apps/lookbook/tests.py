"""스코어링 순수 함수 테스트.

여기만 테스트하는 이유는 순위가 **틀려도 그럴듯한 값이 나오기** 때문이다.
6칸이 채워지기만 하면 화면은 멀쩡해 보여서 아무도 눈치채지 못한다.
"""

from django.test import SimpleTestCase

from apps.lookbook import composition, jobs, progress, scoring, storage
from apps.lookbook.jobs import JobState
from apps.lookbook.scoring import ProductSignals, ReasonCode, ScoredCandidate


class ScoreTest(SimpleTestCase):
    def test_체류시간이_가장_강한_신호다(self):
        dwelled = scoring.score("p_1", ProductSignals(dwell_ms=120_000))
        revisited = scoring.score("p_2", ProductSignals(views=3))

        self.assertGreater(dwelled.score, revisited.score)

    def test_반복_조회는_3회에서_멈춘다(self):
        three = scoring.score("p_1", ProductSignals(views=3))
        ten = scoring.score("p_2", ProductSignals(views=10))

        self.assertEqual(three.score, ten.score)

    def test_비선호_태그는_점수를_깎는다(self):
        plain = scoring.score("p_1", ProductSignals(dwell_ms=120_000))
        avoided = scoring.score("p_2", ProductSignals(dwell_ms=120_000, avoided_tags=2))

        self.assertLess(avoided.score, plain.score)

    def test_점수는_음수로_내려가지_않는다(self):
        self.assertEqual(scoring.score("p_1", ProductSignals(avoided_tags=2)).score, 0.0)

    def test_신호가_없으면_0점이다(self):
        self.assertEqual(scoring.score("p_1", ProductSignals()).score, 0.0)


class ReasonCodeTest(SimpleTestCase):
    def test_가장_크게_기여한_항목이_근거가_된다(self):
        scored = scoring.score("p_1", ProductSignals(dwell_ms=120_000, views=1))

        self.assertEqual(scored.reason_code, ReasonCode.MOST_DWELLED)

    def test_대화에서_물어본_상품은_그_근거를_단다(self):
        scored = scoring.score("p_1", ProductSignals(chat_mentions=2, views=1))

        self.assertEqual(scored.reason_code, ReasonCode.CHAT_MENTIONED)

    def test_문구가_모든_코드에_있다(self):
        scored = scoring.score("p_1", ProductSignals(is_new=True))

        self.assertEqual(scored.reason_code, ReasonCode.NEW_ARRIVAL)
        self.assertEqual(scored.reason, "이번 시즌 신상품")


class RankTest(SimpleTestCase):
    def _fillers(self, count: int) -> list[ScoredCandidate]:
        return [
            ScoredCandidate(product_id=f"f_{index}", score=0.0, reason_code=ReasonCode.POPULAR)
            for index in range(count)
        ]

    def test_신호가_하나도_없어도_6개를_채운다(self):
        ranked = scoring.rank([], self._fillers(10))

        self.assertEqual(len(ranked), scoring.CANDIDATE_COUNT)

    def test_상품이_모자라면_있는_만큼만_준다(self):
        ranked = scoring.rank([], self._fillers(3))

        self.assertEqual(len(ranked), 3)

    def test_점수가_높은_순으로_정렬한다(self):
        scored = [
            scoring.score("p_low", ProductSignals(views=1)),
            scoring.score("p_high", ProductSignals(dwell_ms=120_000)),
        ]

        ranked = scoring.rank(scored, self._fillers(6))

        self.assertEqual(ranked[0].product_id, "p_high")

    def test_같은_방문은_항상_같은_순서를_준다(self):
        scored = [
            scoring.score("p_b", ProductSignals(views=1)),
            scoring.score("p_a", ProductSignals(views=1)),
        ]

        first = [item.product_id for item in scoring.rank(scored, self._fillers(6))]
        second = [item.product_id for item in scoring.rank(scored, self._fillers(6))]

        self.assertEqual(first, second)
        self.assertEqual(first[:2], ["p_a", "p_b"])  # 동점은 id 순으로 고정

    def test_채운_자리가_중복되지_않는다(self):
        scored = [scoring.score("f_0", ProductSignals(dwell_ms=60_000))]

        ranked = scoring.rank(scored, self._fillers(10))

        self.assertEqual(len({item.product_id for item in ranked}), scoring.CANDIDATE_COUNT)


class ProgressTest(SimpleTestCase):
    def test_대기_중에는_10퍼센트에_머문다(self):
        result = progress.interpolate(is_running=False, is_done=False, elapsed_sec=0, expected_sec=25)

        self.assertEqual(result.progress, progress.PROGRESS_QUEUED)
        self.assertEqual(result.stage, progress.STAGE_COMPOSE)

    def test_시간이_지나면_진행률이_올라간다(self):
        early = progress.interpolate(is_running=True, is_done=False, elapsed_sec=1, expected_sec=25)
        late = progress.interpolate(is_running=True, is_done=False, elapsed_sec=20, expected_sec=25)

        self.assertGreater(late.progress, early.progress)

    def test_끝나기_전에는_90퍼센트를_넘지_않는다(self):
        result = progress.interpolate(is_running=True, is_done=False, elapsed_sec=9999, expected_sec=25)

        self.assertEqual(result.progress, progress.PROGRESS_CAP)

    def test_완료되면_100퍼센트로_점프한다(self):
        result = progress.interpolate(is_running=False, is_done=True, elapsed_sec=9999, expected_sec=25)

        self.assertEqual(result.progress, progress.PROGRESS_DONE)

    def test_예상시간이_0이어도_죽지_않는다(self):
        result = progress.interpolate(is_running=True, is_done=False, elapsed_sec=5, expected_sec=0)

        self.assertEqual(result.progress, progress.PROGRESS_CAP)

    def test_단계마다_문구가_있다(self):
        for stage in (progress.STAGE_COMPOSE, progress.STAGE_RENDER, progress.STAGE_FINALIZE):
            self.assertTrue(progress.STAGE_STEPS[stage])

    def test_완료가_가까워지면_더_자주_묻는다(self):
        self.assertEqual(progress.poll_after_ms(3), progress.POLL_SLOW_MS)
        self.assertEqual(progress.poll_after_ms(20), progress.POLL_FAST_MS)


class RetryableTest(SimpleTestCase):
    def test_타임아웃은_다시_시도할_수_있다(self):
        state = JobState(job_id="job_1", share_slug="look-1", error_code="GEN_TIMEOUT")

        self.assertTrue(state.is_retryable)

    def test_사진이_막힌_경우는_재시도해도_소용없다(self):
        state = JobState(job_id="job_1", share_slug="look-1", error_code=jobs.BLOCKED_ERROR)

        self.assertFalse(state.is_retryable)

    def test_에러가_없으면_재시도_대상이_아니다(self):
        self.assertFalse(JobState(job_id="job_1", share_slug="look-1").is_retryable)


class UploadKeyTest(SimpleTestCase):
    def test_확장자는_선언된_타입에서_뽑는다(self):
        self.assertTrue(storage.new_photo_key("image/jpeg").endswith(".jpg"))
        self.assertTrue(storage.new_photo_key("image/png").endswith(".png"))
        self.assertTrue(storage.new_photo_key("image/webp").endswith(".webp"))

    def test_키는_날짜_경로_아래_무작위_이름이다(self):
        key = storage.new_photo_key("image/jpeg")

        self.assertTrue(key.startswith(f"{storage.PHOTO_PREFIX}/"))
        self.assertEqual(len(key.split("/")), 5)  # photos/YYYY/MM/DD/name.jpg

    def test_매번_다른_키가_나온다(self):
        keys = {storage.new_photo_key("image/jpeg") for _ in range(50)}

        self.assertEqual(len(keys), 50)

    def test_마스크는_사진과_짝이_되는_키를_쓴다(self):
        photo = "photos/2026/08/17/9c1f4a2b.jpg"

        self.assertEqual(storage.mask_key_for(photo), "photos/2026/08/17/9c1f4a2b_mask.png")

    def test_마스크는_원본_확장자와_무관하게_png다(self):
        self.assertTrue(storage.mask_key_for("photos/2026/08/17/a.webp").endswith("_mask.png"))


class SeedTest(SimpleTestCase):
    def test_첫_컷은_같은_방문에서_항상_같다(self):
        first = composition.seed_for("v_abc", attempt=1)
        second = composition.seed_for("v_abc", attempt=1)

        self.assertEqual(first, second)

    def test_사람마다_다른_seed가_나온다(self):
        self.assertNotEqual(composition.seed_for("v_abc", 1), composition.seed_for("v_xyz", 1))

    def test_재생성은_매번_달라진다(self):
        seeds = {composition.seed_for("v_abc", attempt=2) for _ in range(20)}

        self.assertGreater(len(seeds), 1)


class FakeComposition:
    def __init__(self, code, min_face, max_face):
        self.code = code
        self.min_face = min_face
        self.max_face = max_face

    def accepts(self, face_ratio):
        return face_ratio is None or self.min_face <= face_ratio <= self.max_face


class CompositionChoiceTest(SimpleTestCase):
    def setUp(self):
        self.all = [
            FakeComposition("close_up", 0.15, 1.00),
            FakeComposition("half_body", 0.05, 0.35),
            FakeComposition("wide", 0.00, 0.15),
            FakeComposition("product_focus", 0.00, 1.00),
        ]

    def test_얼굴이_크면_와이드는_후보에서_빠진다(self):
        picked = {composition.choose(self.all, 0.5, seed).code for seed in range(20)}

        self.assertNotIn("wide", picked)

    def test_얼굴을_못_찾으면_전부_후보다(self):
        picked = {composition.choose(self.all, None, seed).code for seed in range(20)}

        self.assertEqual(len(picked), len(self.all))

    def test_같은_seed는_같은_구도를_고른다(self):
        first = composition.choose(self.all, 0.2, seed=7)
        second = composition.choose(self.all, 0.2, seed=7)

        self.assertEqual(first.code, second.code)

    def test_이미_쓴_구도는_피한다(self):
        picked = composition.choose(self.all, None, seed=0, used_codes=("close_up",))

        self.assertNotEqual(picked.code, "close_up")

    def test_후보가_다_소진되면_다시_쓴다(self):
        used = tuple(item.code for item in self.all)

        self.assertIsNotNone(composition.choose(self.all, None, seed=0, used_codes=used))


class MagicByteTest(SimpleTestCase):
    def test_jpeg를_알아본다(self):
        self.assertTrue(storage.is_image(b"\xff\xd8\xff\xe0" + b"\x00" * 8))

    def test_png를_알아본다(self):
        self.assertTrue(storage.is_image(b"\x89PNG\r\n\x1a\n" + b"\x00" * 4))

    def test_webp를_알아본다(self):
        self.assertTrue(storage.is_image(b"RIFF\x00\x00\x00\x00WEBP"))

    def test_이미지가_아니면_거른다(self):
        """content_type은 클라이언트 선언값이라 image/jpeg라 해놓고 아무거나 올릴 수 있다."""
        self.assertFalse(storage.is_image(b"<!DOCTYPE ht"))
