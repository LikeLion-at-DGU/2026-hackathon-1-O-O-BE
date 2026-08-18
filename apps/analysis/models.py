"""분석 파생 데이터. 원본(events)과 분리해 두어 추천 로직이 바뀌어도 재분석할 수 있다."""

from django.db import models

from common.ids import gen_report_slug


class ReportStatus(models.TextChoices):
    PENDING = "pending", "분석 중"
    READY = "ready", "완료"
    FAILED = "failed", "실패"  # 무한 pending 대신 프론트가 재시도 안내를 띄울 수 있게


class Character(models.Model):
    """16유형 캐릭터. 이미지는 사전 제작 16장이라 ⑦단계가 조회 한 번으로 끝난다.

    생성 API를 부르지 않으므로 워커 지연이 늘지 않고, 같은 유형이면 항상 같은
    이미지가 나와 리포트 "박제"가 유지된다.
    """

    type_code = models.CharField(primary_key=True, max_length=4)  # 예: CNPD
    name = models.CharField(max_length=50)
    one_liner = models.CharField(max_length=200)
    image_url = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["type_code"]

    def __str__(self) -> str:
        return f"{self.type_code} {self.name}"


class TasteProfile(models.Model):
    """Visit 단위 분석 결과. UUID에 장기 누적하지 않는다(재방문 마이페이지 없음)."""

    # visitor는 visit.visitor로 도달한다. 같은 사실을 두 곳에 두면 어긋날 때 무엇이 진실인지 모른다.
    visit = models.OneToOneField("visits.Visit", related_name="taste_profile", on_delete=models.CASCADE)
    vector = models.JSONField(default=dict)  # 속성별 관심도
    axis_scores = models.JSONField(default=dict)  # 16유형 4축 점수
    character_type = models.CharField(max_length=4, blank=True)  # 예: CNPD
    confidence = models.FloatField(default=0.0)
    # 대화에서 뽑은 선호·비선호·구매의도·망설임. 리포트에 다 노출하지는 않지만
    # /admin/chat-insights가 "구매 망설임 요인"을 집계할 유일한 재료라 버리지 않는다.
    insight = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"TasteProfile({self.visit_id}, {self.character_type})"


class Report(models.Model):
    """완성된 리포트를 박제한 것. slug로 언제 열어도 재계산 없이 같은 화면이 나온다."""

    slug = models.CharField(primary_key=True, max_length=40, default=gen_report_slug, editable=False)
    visit = models.OneToOneField("visits.Visit", related_name="report", on_delete=models.CASCADE)
    status = models.CharField(max_length=10, choices=ReportStatus.choices, default=ReportStatus.PENDING)
    # 상품 스냅샷(이름·이미지·가격·구매링크)을 함께 박제한다. 집에서 열 때는
    # visit_token이 없어 GET /products/{id}를 부를 수 없기 때문이다.
    payload = models.JSONField(default=dict)
    failure_reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"Report({self.slug}, {self.status})"
