from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from api.authentication import ANONYMOUS_UUID_HEADER
from api.permissions import IsVisitAuthenticated
from api.scoping import assert_own_visit
from apps.chat.messages import append_hypothesis
from apps.chat.triggers import evaluate
from apps.events.serializers import EventBatchResultSerializer, EventBatchSerializer
from apps.events.services import append_batch
from apps.visits.models import Visit
from apps.visits.services import parse_uuid, touch


class EventBatchView(APIView):
    """POST /api/v1/events — 행동 이벤트 배치 수집.

    클라이언트가 모아뒀다가 주기적으로, 또는 페이지를 떠날 때 보낸다.
    저장은 append-only이고 event_id로 중복을 제거하므로 재전송이 안전하다.

    종료된 방문도 받는다. 화보가 /finish 이후에 일어나기 때문이며, 대신 어떤 타입을
    받을지는 services의 화이트리스트가 가른다. 여기서 막으면 종료 직전 구간이
    통째로 유실되는데, 그 구간이 전환 분석에서 가장 중요하다.
    """

    permission_classes = [IsVisitAuthenticated]

    @extend_schema(
        request=EventBatchSerializer,
        responses={202: EventBatchResultSerializer},
        parameters=[
            OpenApiParameter(
                name="X-Anonymous-UUID",
                location=OpenApiParameter.HEADER,
                required=True,
                description="클라이언트가 보관하는 익명 UUID. visit token의 방문자와 일치해야 한다.",
            )
        ],
        tags=["Event"],
    )
    def post(self, request):
        serializer = EventBatchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        visit = assert_own_visit(request, serializer.validated_data["visit_id"])
        self._assert_visitor_matches(request, visit)

        result = append_batch(visit, serializer.validated_data["events"])
        touch(visit)
        # 행동이 쌓인 직후가 관찰의 유일한 시점이다. 조건에 걸리면 가설 말풍선을
        # 타임라인에 넣고, 프론트는 GET /chat/messages의 pending_action에서 발견한다.
        # 관람이 끝난 뒤(화보 구간)에는 물어볼 화면이 없으므로 관찰도 멈춘다.
        if visit.is_open:
            hypothesis = evaluate(visit)
            if hypothesis is not None:
                append_hypothesis(visit, hypothesis)
        return Response(result, status=status.HTTP_202_ACCEPTED)

    def _assert_visitor_matches(self, request, visit: Visit) -> None:
        """명세가 이 API에 X-Anonymous-UUID를 필수로 정의했다.

        토큰만으로도 방문자를 알 수 있지만, 두 값이 어긋나면 클라이언트가 다른
        브라우저의 토큰을 들고 있다는 뜻이므로 그대로 저장하면 남의 리포트가 오염된다.
        """
        raw = request.META.get(ANONYMOUS_UUID_HEADER)
        if not raw:
            raise ValidationError({"X-Anonymous-UUID": ["헤더가 필요합니다."]})
        if parse_uuid(raw) != visit.visitor_id:
            raise PermissionDenied("X-Anonymous-UUID가 visit token의 방문자와 일치하지 않습니다.")
