"""토큰 범위 검사.

클라이언트가 보낸 visit_id를 그대로 믿으면 남의 방문에 이벤트·대화를 심을 수 있고,
그 사람의 리포트가 오염된다. 여러 앱이 같은 규칙을 쓰므로 한 곳에 둔다.
"""

from rest_framework.exceptions import PermissionDenied

from apps.visits.models import Visit


def assert_own_visit(request, visit_id: str) -> Visit:
    """토큰이 가리키는 방문과 일치할 때만 그 Visit을 돌려준다."""
    visit = request.auth
    if visit_id != visit.id:
        raise PermissionDenied("토큰이 가리키는 방문이 아닙니다.")
    return visit
