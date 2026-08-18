"""화보 1건과 구도 마스터.

`attempt`로 재생성 이력을 남긴다. 이전 화보를 지우지 않는 이유는 **이미 공유한
링크가 살아 있어야** 하기 때문이다. 남이 열었을 때 다른 화보가 보이면 박제 위반이다.
"""

from django.db import models

from common.ids import gen_id


def new_share_slug() -> str:
    """공유 링크의 열쇠. 재생성할 때마다 새로 발급한다."""
    return gen_id("look")


def new_job_id() -> str:
    return gen_id("job")


class LookbookStatus(models.TextChoices):
    QUEUED = "queued", "대기"
    PROCESSING = "processing", "생성 중"
    READY = "ready", "완료"
    FAILED = "failed", "실패"


class Composition(models.Model):
    """구도 마스터. 4행 고정이고 전 무드가 공용으로 쓴다.

    DB에 두는 이유는 레퍼런스·범위를 조정할 때 배포가 필요 없게 하려는 것이다.
    """

    code = models.CharField(primary_key=True, max_length=20)  # close_up / half_body / ...
    name = models.CharField(max_length=50)
    # 얼굴이 화면에서 차지하는 비율의 허용 범위. 정면 상반신을 찍었는데 전신 와이드를
    # 요구하면 없는 몸을 만들어내야 해서 결과가 왜곡된다.
    min_face = models.FloatField()
    max_face = models.FloatField()
    reference_url = models.CharField(max_length=300, blank=True)
    prompt = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["code"]

    def __str__(self) -> str:
        return f"{self.code}({self.min_face}~{self.max_face})"

    def accepts(self, face_ratio: float | None) -> bool:
        """얼굴 비율을 모르면(검출 실패) 모든 구도를 후보로 본다."""
        if face_ratio is None:
            return True
        return self.min_face <= face_ratio <= self.max_face


class Lookbook(models.Model):
    """화보 1건. 생성 요청 시점에 만들어지고 워커가 결과를 채운다."""

    share_slug = models.CharField(primary_key=True, max_length=40, default=new_share_slug, editable=False)
    report = models.ForeignKey("analysis.Report", related_name="lookbooks", on_delete=models.CASCADE)
    job_id = models.CharField(max_length=40, default=new_job_id, editable=False, db_index=True)
    attempt = models.PositiveSmallIntegerField()
    status = models.CharField(max_length=12, choices=LookbookStatus.choices, default=LookbookStatus.QUEUED)

    product_ids = models.JSONField(default=list)
    photo_key = models.CharField(max_length=200)
    mask_key = models.CharField(max_length=200, blank=True)
    composition = models.ForeignKey(
        Composition, related_name="lookbooks", on_delete=models.PROTECT, null=True, blank=True
    )
    # 무드 스냅샷 + _meta.seed. seed를 안 남기면 나온 결과를 되짚을 수 없다.
    mood_payload = models.JSONField(default=dict)
    image_url = models.CharField(max_length=300, blank=True)
    error_code = models.CharField(max_length=40, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            # [다시 돌리기] 연타로 같은 attempt가 두 번 계산되면 이미지 생성 비용이 두 배로 나간다.
            models.UniqueConstraint(fields=["report", "attempt"], name="uniq_report_attempt")
        ]

    def __str__(self) -> str:
        return f"Lookbook({self.share_slug}, {self.attempt}회차, {self.status})"
