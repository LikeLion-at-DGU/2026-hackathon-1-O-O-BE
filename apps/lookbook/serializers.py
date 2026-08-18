"""문서용 응답 스키마. 실제 조립은 candidates.build()가 한다."""

from django.conf import settings
from rest_framework import serializers

from apps.lookbook.storage import ALLOWED_CONTENT_TYPES


class CandidateItemSerializer(serializers.Serializer):
    product_id = serializers.CharField()
    name = serializers.CharField()
    category = serializers.CharField(help_text="화면 표기용 한국어 라벨")
    thumbnail = serializers.CharField(allow_null=True)
    cutout_url = serializers.CharField(allow_blank=True, help_text="배경 제거 PNG. 화보 합성에 쓴다")
    score = serializers.FloatField()
    reason_code = serializers.CharField(help_text="most_dwelled / revisited / chat_mentioned / ...")
    reason = serializers.CharField(help_text="카드 뱃지에 그대로 노출하는 문구")


class CandidateListSerializer(serializers.Serializer):
    # 지금은 1개지만 원안은 최대 4개였다. 서버가 내려주면 늘릴 때 프론트를 안 고쳐도 된다.
    max_select = serializers.IntegerField()
    min_select = serializers.IntegerField()
    preselected = serializers.ListField(child=serializers.CharField())
    items = CandidateItemSerializer(many=True, help_text="정확히 6개")


class JobStatusSerializer(serializers.Serializer):
    """P02-c 로딩 화면이 3초(또는 1.2초)마다 받는 응답."""

    job_id = serializers.CharField()
    status = serializers.CharField(help_text="queued / processing / ready / failed")
    progress = serializers.FloatField(help_text="0~1. 완료 전에는 0.9를 넘지 않는다")
    stage = serializers.CharField(help_text="compose / render / finalize — 프론트는 이 코드로 분기한다")
    step = serializers.CharField(help_text="화면에 그대로 띄우는 한국어 문구")
    share_slug = serializers.CharField(allow_null=True)
    attempt = serializers.IntegerField()
    error_code = serializers.CharField(allow_null=True)
    retryable = serializers.BooleanField(help_text="true면 재생성 횟수를 깎지 않고 다시 시도한다")
    poll_after_ms = serializers.IntegerField(help_text="다음 폴링까지 기다릴 시간. 서버가 정한다")


class PresignRequestSerializer(serializers.Serializer):
    """촬영 직후 한 번 호출한다. 파일명은 받지 않는다 — 키는 서버가 만든다."""

    content_type = serializers.CharField()
    byte_size = serializers.IntegerField(min_value=1)

    def validate_content_type(self, value: str) -> str:
        if value not in ALLOWED_CONTENT_TYPES:
            raise serializers.ValidationError("unsupported_type")
        return value

    def validate_byte_size(self, value: int) -> int:
        """얼굴 사진 한 장에 5MB를 넘길 이유가 없다. 넘으면 업로드도 생성도 느려진다."""
        if value > settings.PHOTO_MAX_BYTES:
            raise serializers.ValidationError("file_too_large")
        return value


class PresignResponseSerializer(serializers.Serializer):
    photo_key = serializers.CharField()
    photo_upload_url = serializers.CharField()
    mask_key = serializers.CharField()
    mask_upload_url = serializers.CharField()
    headers = serializers.DictField(help_text="각 PUT에 그대로 실어야 하는 헤더")
    expires_in = serializers.IntegerField()


class PhotoMetaSerializer(serializers.Serializer):
    """브라우저에서 얼굴 검출로 얻은 값. 검출이 실패해도 서비스는 정상 동작해야 한다."""

    face_count = serializers.IntegerField(required=False, min_value=0)
    face_ratio = serializers.FloatField(required=False, min_value=0.0, max_value=1.0)
    face_center = serializers.ListField(child=serializers.FloatField(), required=False)


class LookbookCreateSerializer(serializers.Serializer):
    """생성·재생성 공용. 재생성은 같은 값을 그대로 다시 보내면 된다."""

    product_ids = serializers.ListField(child=serializers.CharField(), allow_empty=False)
    photo_key = serializers.CharField()
    # 인물 실루엣. 없으면 체형 보존이 약해질 뿐 생성 자체는 된다.
    mask_key = serializers.CharField(required=False, allow_blank=True, default="")
    consent = serializers.BooleanField()
    photo_meta = PhotoMetaSerializer(required=False, default=dict)


class LookbookCreateResponseSerializer(serializers.Serializer):
    job_id = serializers.CharField()
    # 로딩 중 앱을 닫았다 켜도 복구되도록 프론트가 미리 URL을 바꿔둘 수 있게 준다.
    share_slug = serializers.CharField()
    attempt = serializers.IntegerField()
    remaining_regenerations = serializers.IntegerField()
    poll_after_ms = serializers.IntegerField()


class LookbookProductSerializer(serializers.Serializer):
    product_id = serializers.CharField()
    name = serializers.CharField()
    image_url = serializers.CharField(allow_null=True)
    price = serializers.IntegerField()
    detail_url = serializers.CharField()


class LookbookDetailSerializer(serializers.Serializer):
    """완성 화보. mood·stats·muse_no는 생성 시점에 박제된 값을 그대로 낸다."""

    share_slug = serializers.CharField()
    attempt = serializers.IntegerField()
    image_url = serializers.CharField()
    width = serializers.IntegerField()
    height = serializers.IntegerField()
    muse_no = serializers.IntegerField(allow_null=True)
    muse_label = serializers.CharField(allow_null=True)
    venue = serializers.CharField(allow_null=True)
    season = serializers.CharField(allow_null=True)
    mood = serializers.DictField(help_text="code · name · reason · palette")
    stats = serializers.ListField(help_text="key · label · value. 프론트는 순회만 한다")
    products = LookbookProductSerializer(many=True)
    report_slug = serializers.CharField()
    created_at = serializers.DateTimeField()
