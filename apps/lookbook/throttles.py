"""업로드 남용 방지.

PUT /uploads/{key}는 인증이 없는 유일한 쓰기 경로다. KEY_PATTERN에 맞는 키를
임의로 만들어 5MB짜리를 반복 업로드하면 디스크가 찬다. 키를 추측할 필요조차
없으므로(자기가 지어내면 된다) 속도 제한이 유일한 방어다.
"""

from rest_framework.throttling import AnonRateThrottle, SimpleRateThrottle


class UploadPresignThrottle(SimpleRateThrottle):
    """방문 단위. 정상 플로우는 촬영 1회당 presign 1번이다."""

    scope = "upload_presign"

    def get_cache_key(self, request, view) -> str | None:
        visit = request.auth
        return self.cache_format % {"scope": self.scope, "ident": visit.id} if visit else None


class UploadReceiveThrottle(AnonRateThrottle):
    """IP 단위. 매장 와이파이는 여러 손님이 한 IP를 쓰므로 빠듯하게 잡으면
    정상 손님이 막힌다 — 디스크 고갈만 막을 만큼 느슨하게 둔다."""

    scope = "upload_receive"
