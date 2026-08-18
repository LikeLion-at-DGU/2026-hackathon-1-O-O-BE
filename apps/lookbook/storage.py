"""업로드 키 생성과 presign URL 발급.

사진 바이트는 Django를 지나가지 않는다. 서버로 받으면 매장 와이파이에서 500KB
올리는 3초 동안 워커 프로세스가 통째로 묶이기 때문이다. 서버는 URL만 발급하고
브라우저가 스토리지로 직행한다.
"""

import uuid
from dataclasses import dataclass

from django.conf import settings
from django.utils import timezone

PHOTO_PREFIX = "photos"
MASK_SUFFIX = "_mask"
MASK_CONTENT_TYPE = "image/png"

# 확장자는 선언된 content_type에서 뽑는다. 클라이언트 파일명은 쓰지 않는다.
EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}
ALLOWED_CONTENT_TYPES = tuple(EXTENSIONS)

BACKEND_DEV = "dev"
BACKEND_S3 = "s3"


@dataclass(frozen=True)
class UploadTarget:
    key: str
    upload_url: str
    content_type: str


def new_photo_key(content_type: str) -> str:
    """서버가 만든다. 클라이언트 파일명을 쓰면 경로 조작(../../)과 한글·이모지 파일명이
    그대로 들어오는데, UUID로 덮으면 그 문제가 통째로 사라지고 키를 추측할 수 없게 되는
    효과도 함께 온다."""
    today = timezone.now()
    name = uuid.uuid4().hex[:16]
    return f"{PHOTO_PREFIX}/{today:%Y/%m/%d}/{name}{EXTENSIONS[content_type]}"


def mask_key_for(photo_key: str) -> str:
    """마스크는 사진과 같은 이름에 접미사만 붙인다. 둘이 짝이라는 게 키에서 읽힌다."""
    base = photo_key.rsplit(".", 1)[0]
    return f"{base}{MASK_SUFFIX}.png"


def presign_put(key: str, content_type: str) -> UploadTarget:
    """PUT용 업로드 URL. 만료는 settings.UPLOAD_URL_TTL_SEC."""
    if settings.STORAGE_BACKEND == BACKEND_S3:
        url = _presign_s3(key, content_type)
    else:
        url = _presign_dev(key)
    return UploadTarget(key=key, upload_url=url, content_type=content_type)


def _presign_dev(key: str) -> str:
    """버킷이 없는 개발 환경용. 계약(키·URL·만료)을 그대로 확인할 수 있게 하되,
    **실제로 PUT을 받지는 않는다.** 받는 척하면 업로드가 됐다고 착각하게 된다."""
    return f"{settings.UPLOAD_DEV_BASE_URL}/{key}?dev-unsigned=1&expires_in={settings.UPLOAD_URL_TTL_SEC}"


def _presign_s3(key: str, content_type: str) -> str:
    """R2·S3 공통(R2가 S3 호환 API를 쓴다). boto3는 이 백엔드를 켤 때만 필요하다."""
    import boto3

    client = boto3.client(
        "s3",
        endpoint_url=settings.STORAGE_ENDPOINT_URL or None,
        aws_access_key_id=settings.STORAGE_ACCESS_KEY,
        aws_secret_access_key=settings.STORAGE_SECRET_KEY,
        region_name=settings.STORAGE_REGION,
    )
    return client.generate_presigned_url(
        "put_object",
        Params={"Bucket": settings.STORAGE_BUCKET, "Key": key, "ContentType": content_type},
        ExpiresIn=settings.UPLOAD_URL_TTL_SEC,
    )


# 파일 앞부분 시그니처. presign의 content_type은 클라이언트가 선언한 값이라 실제 내용과
# 무관하다. image/jpeg라고 해놓고 아무거나 올릴 수 있어서 바이트로 확인한다.
MAGIC_BYTES = 12
_SIGNATURES = (
    (b"\xff\xd8\xff", 0),  # JPEG
    (b"\x89PNG\r\n\x1a\n", 0),  # PNG
    (b"WEBP", 8),  # RIFF....WEBP
)


class UploadNotFound(LookupError):
    """presign만 받고 실제로 올리지 않았다."""


class NotAnImage(ValueError):
    """올라온 바이트가 이미지가 아니다."""


def verify_upload(key: str) -> None:
    """실제로 올라왔는지, 진짜 이미지인지 확인한다.

    dev 백엔드는 확인할 대상이 없으므로 건너뛴다. 없는 것을 있다고 답하면 안 되고,
    없다고 400을 내면 버킷이 생기기 전까지 생성 자체를 못 하게 된다.
    """
    if settings.STORAGE_BACKEND != BACKEND_S3:
        return

    import boto3
    from botocore.exceptions import ClientError

    client = boto3.client(
        "s3",
        endpoint_url=settings.STORAGE_ENDPOINT_URL or None,
        aws_access_key_id=settings.STORAGE_ACCESS_KEY,
        aws_secret_access_key=settings.STORAGE_SECRET_KEY,
        region_name=settings.STORAGE_REGION,
    )
    try:
        head = client.get_object(Bucket=settings.STORAGE_BUCKET, Key=key, Range=f"bytes=0-{MAGIC_BYTES - 1}")
    except ClientError as error:
        raise UploadNotFound(key) from error

    if not is_image(head["Body"].read(MAGIC_BYTES)):
        raise NotAnImage(key)


def is_image(head: bytes) -> bool:
    """앞 12바이트로 판정한다. 순수 함수라 테스트가 쉽다."""
    return any(head[offset : offset + len(sig)] == sig for sig, offset in _SIGNATURES)
