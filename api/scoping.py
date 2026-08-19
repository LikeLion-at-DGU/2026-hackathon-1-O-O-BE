"""토큰 범위 검사.

클라이언트가 보낸 visit_id를 그대로 믿으면 남의 방문에 이벤트·대화를 심을 수 있고,
그 사람의 리포트가 오염된다. 여러 앱이 같은 규칙을 쓰므로 한 곳에 둔다.
"""

from rest_framework.exceptions import PermissionDenied

from apps.visits.models import Visit


def assert_own_visit(request, visit_id: str | None = None) -> Visit:
    """토큰이 가리키는 방문을 돌려준다. visit_id를 함께 보냈으면 일치도 확인한다.

    방문을 확정하는 것은 토큰이고 visit_id는 대조용이다. 그래서 안 보내도 처리할 수
    있어야 한다 — /finish는 이미 body에 visit_id 없이 동작하는데 /events만 필수로
    두는 바람에, 같은 모양으로 보내는 클라이언트가 한쪽에서만 400을 맞았다.
    """
    visit = request.auth
    if visit_id and visit_id != visit.id:
        raise PermissionDenied("토큰이 가리키는 방문이 아닙니다.")
    return visit
