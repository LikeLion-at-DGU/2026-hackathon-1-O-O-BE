"""사용자 API용 퍼미션. 기본 권한이 IsAuthenticated로 잠겨 있으므로 여기서 명시적으로 연다."""

from rest_framework.permissions import BasePermission

from apps.visits.models import Visit


class IsVisitAuthenticated(BasePermission):
    """유효한 X-Visit-Token이 있으면 통과. 로그인은 필요 없다."""

    message = "유효하지 않거나 만료된 visit token 입니다."

    def has_permission(self, request, view) -> bool:
        return isinstance(request.auth, Visit)


class IsOpenVisit(IsVisitAuthenticated):
    """진행 중인 Visit만 통과. 종료된 Visit에는 이벤트·대화를 더 쌓지 않는다."""

    message = "이미 종료된 관람입니다."

    def has_permission(self, request, view) -> bool:
        return super().has_permission(request, view) and request.auth.is_open
