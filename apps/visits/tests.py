"""방문 수명 테스트. 토큰이 언제 죽고 언제 이어지는지가 전부 여기 달려 있다.

만료 규칙이 틀리면 관람 중에 토큰이 끊기거나(손님이 매장 한가운데서 튕긴다),
반대로 영원히 안 죽는다. 둘 다 화면에서는 한참 뒤에야 드러난다.

시간은 `.update()`로 되돌린다. started_at·last_seen_at이 auto_now_add라 생성
시점에 지정할 수 없고, 이것 하나 때문에 freezegun을 의존성에 넣을 이유는 없다.
"""

from datetime import timedelta

from django.conf import settings
from django.test import TestCase
from django.utils import timezone

from apps.catalog.models import Store
from apps.visits import services
from apps.visits.models import Visit


def backdate(visit: Visit, **fields) -> Visit:
    Visit.objects.filter(pk=visit.pk).update(**fields)
    visit.refresh_from_db()
    return visit


def hours_ago(hours: float):
    return timezone.now() - timedelta(hours=hours)


class VisitTestBase(TestCase):
    def setUp(self):
        self.store = Store.objects.create(name="테스트 매장")
        self.visitor, _ = services.resolve_or_issue(None)

    def start(self) -> Visit:
        return services.start(self.visitor, self.store)


class ExpiryTest(VisitTestBase):
    """만료는 진입이 아니라 마지막 활동에서 잰다."""

    def test_오래_머물러도_활동_중이면_살아_있다(self):
        # 진입 기준으로 재면 3시간을 넘긴 순간 관람 중에도 끊긴다.
        visit = backdate(self.start(), started_at=hours_ago(5), last_seen_at=timezone.now())
        self.assertFalse(visit.is_expired)

    def test_마지막_활동_후_기준_시간이_지나면_만료된다(self):
        stale = timezone.now() - settings.VISIT_STALE_AFTER - timedelta(minutes=1)
        visit = backdate(self.start(), last_seen_at=stale)
        self.assertTrue(visit.is_expired)

    def test_종료된_관람도_토큰은_살아_있다(self):
        """퇴장 뒤에 화보를 만들고 다시 돌려야 한다. 만료의 근거는 시간 하나뿐이다."""
        visit = self.start()
        services.expire(visit)
        visit.refresh_from_db()
        self.assertFalse(visit.is_open)
        self.assertFalse(visit.is_expired)


class TouchTest(VisitTestBase):
    """활동 시각 갱신. 인증마다 불리므로 매번 저장하면 읽기에도 쓰기가 붙는다."""

    def test_시간이_지난_뒤_요청하면_갱신된다(self):
        visit = backdate(self.start(), last_seen_at=hours_ago(2))
        before = visit.last_seen_at
        services.touch(visit)
        visit.refresh_from_db()
        self.assertGreater(visit.last_seen_at, before)

    def test_짧은_간격에는_다시_저장하지_않는다(self):
        visit = self.start()
        before = visit.last_seen_at
        services.touch(visit)
        visit.refresh_from_db()
        self.assertEqual(visit.last_seen_at, before)

    def test_갱신이_만료를_되돌린다(self):
        visit = backdate(self.start(), last_seen_at=hours_ago(2))
        services.touch(visit)
        visit.refresh_from_db()
        self.assertLess(timezone.now() - visit.last_seen_at, timedelta(minutes=1))


class ResumeTest(VisitTestBase):
    """이어하기. 같은 방문을 돌려줄 때는 토큰까지 그대로여야 한다."""

    def test_살아_있는_방문은_이어받는다(self):
        visit = backdate(self.start(), last_seen_at=hours_ago(2))
        self.assertEqual(services.find_resumable(self.visitor), visit)

    def test_만료된_방문은_이어받지_않고_닫는다(self):
        stale = timezone.now() - settings.VISIT_STALE_AFTER - timedelta(minutes=1)
        visit = backdate(self.start(), last_seen_at=stale)

        self.assertIsNone(services.find_resumable(self.visitor))
        visit.refresh_from_db()
        self.assertFalse(visit.is_open)
        # 방치돼 서버가 닫은 방문은 평균 체류시간·리포트 완료율의 분모에서 뺀다.
        self.assertTrue(visit.is_auto_closed)

    def test_열린_방문이_여럿이면_최근_하나만_남기고_닫는다(self):
        older = self.start()
        newer = self.start()

        self.assertEqual(services.find_resumable(self.visitor), newer)
        older.refresh_from_db()
        self.assertFalse(older.is_open)

    def test_새로_시작은_자동_종료로_세지_않는다(self):
        """손님이 이어하기 모달에서 직접 고른 것이라 방치가 아니다."""
        visit = self.start()
        services.expire(visit, auto_closed=False)
        visit.refresh_from_db()
        self.assertFalse(visit.is_open)
        self.assertFalse(visit.is_auto_closed)


class MuseNoTest(VisitTestBase):
    def test_뮤즈_번호는_매장별로_하나씩_올라간다(self):
        first, second = self.start(), self.start()
        self.assertEqual(second.muse_no, first.muse_no + 1)

    def test_다른_매장은_번호를_공유하지_않는다(self):
        other = Store.objects.create(name="다른 매장")
        self.start()
        self.assertEqual(services.start(self.visitor, other).muse_no, 1)

    def test_표시용_라벨은_세_자리로_채운다(self):
        visit = self.start()
        self.assertEqual(visit.muse_label, f"N.{visit.muse_no:03d}")
