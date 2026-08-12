"""visit_token 인증. 토큰 검증의 진실은 이 파일 하나뿐이다.

JWT가 아니라 DB 토큰을 쓴다. 관람 중 토큰이 만료돼도 같은 토큰을 그대로 이어
쓸 수 있어야 하고(이탈 복구), 필요하면 서버가 즉시 무효화할 수 있어야 한다.
"""

from drf_spectacular.extensions import OpenApiAuthenticationExtension
from rest_framework.authentication import BaseAuthentication

from api.exceptions import InvalidVisitToken
from apps.visits.models import Visit

VISIT_TOKEN_HEADER = "HTTP_X_VISIT_TOKEN"


class VisitTokenAuthentication(BaseAuthentication):
    """X-Visit-Token 헤더를 Visit으로 바꾼다.

    DRF의 request.user는 익명 사용자에게 의미가 없으므로 (None, visit) 형태로
    돌려주고, 뷰는 request.auth로 Visit을 받는다. IsAuthenticated는 통과하지
    않으므로 사용자 API는 IsVisitAuthenticated 퍼미션을 쓴다.
    """

    def authenticate(self, request):
        token = request.META.get(VISIT_TOKEN_HEADER)
        if not token:
            return None

        visit = Visit.objects.select_related("visitor", "store").filter(token=token).first()
        if visit is None:
            raise InvalidVisitToken()

        return (None, visit)


class VisitTokenScheme(OpenApiAuthenticationExtension):
    """Swagger UI의 Authorize 버튼에 X-Visit-Token을 노출한다.

    drf-spectacular는 import된 확장만 등록하므로, 인증 클래스와 같은 파일에 둔다.
    (이 모듈은 DEFAULT_AUTHENTICATION_CLASSES 때문에 기동 시 항상 로드된다)
    """

    target_class = "api.authentication.VisitTokenAuthentication"
    name = "VisitToken"

    def get_security_definition(self, auto_schema) -> dict:
        return {
            "type": "apiKey",
            "in": "header",
            "name": "X-Visit-Token",
            "description": "POST /api/v1/enter 응답으로 받은 visit_token 값을 그대로 넣는다.",
        }
