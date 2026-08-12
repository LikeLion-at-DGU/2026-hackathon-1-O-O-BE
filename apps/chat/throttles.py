from rest_framework.throttling import SimpleRateThrottle


class ChatThrottle(SimpleRateThrottle):
    """LLM 남용 방지. 방문 단위로 센다.

    IP 기준으로 세면 매장 와이파이를 함께 쓰는 손님 전체가 한 사람으로 묶인다.
    """

    scope = "chat"

    def get_cache_key(self, request, view) -> str | None:
        visit = request.auth
        return self.cache_format % {"scope": self.scope, "ident": visit.id} if visit else None
