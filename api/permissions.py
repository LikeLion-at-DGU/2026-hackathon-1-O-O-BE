"""사용자 API용 퍼미션. 기본 권한이 IsAuthenticated로 잠겨 있으므로 여기서 명시적으로 연다."""

from rest_framework.permissions import BasePermission

from api.exceptions import InvalidVisitToken
from apps.visits.models import Visit


class IsVisitAuthenticated(BasePermission):
    """유효한 X-Visit-Token이 있으면 통과. 로그인은 필요 없다.

    만료(진입 후 3시간) 판정은 인증 단계가 이미 끝냈으므로 여기서 다시 보지 않는다.

    False를 돌려주지 않고 예외를 던지는 이유: DRF는 인증 정보가 없을 때 401을
    403으로 강등하는데, 명세는 토큰 누락·만료·위조를 모두 401 INVALID_VISIT_TOKEN
    으로 정의했다.
    """

    def has_permission(self, request, view) -> bool:
        if not isinstance(request.auth, Visit):
            raise InvalidVisitToken()
        return True


class IsOpenVisit(IsVisitAuthenticated):
    """관람이 진행 중인 Visit만 통과. 종료된 관람에는 대화를 더 쌓지 않는다.

    토큰 자체는 유효하므로 401이 아니라 403이다. 종료 뒤에도 토큰은 화보를 위해
    살아 있으니, 이건 만료가 아니라 "지금 이 화면을 쓸 수 있는가"의 문제다.

    /events는 이걸 쓰지 않는다. 화보 이벤트를 받아야 해서 타입별 화이트리스트로 가른다.
    """

    message = "이미 종료된 관람입니다."

    def has_permission(self, request, view) -> bool:
        super().has_permission(request, view)
        return request.auth.is_open
