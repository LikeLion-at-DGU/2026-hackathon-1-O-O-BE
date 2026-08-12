from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from api.authentication import ANONYMOUS_UUID_HEADER
from api.permissions import IsOpenVisit
from apps.events.serializers import EventBatchResultSerializer, EventBatchSerializer
from apps.events.services import append_batch
from apps.visits.models import Visit
from apps.visits.services import parse_uuid, touch


class EventBatchView(APIView):
    """POST /api/v1/events — 행동 이벤트 배치 수집.

    클라이언트가 모아뒀다가 주기적으로, 또는 페이지를 떠날 때 보낸다.
    저장은 append-only이고 event_id로 중복을 제거하므로 재전송이 안전하다.
    """

    permission_classes = [IsOpenVisit]

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

        visit = request.auth
        self._assert_visitor_matches(request, visit)
        if serializer.validated_data["visit_id"] != visit.id:
            # 토큰이 가리키는 방문만 기록할 수 있다. 클라이언트가 보낸 visit_id를 믿지 않는다.
            raise PermissionDenied("다른 방문의 이벤트는 기록할 수 없습니다.")

        result = append_batch(visit, serializer.validated_data["events"])
        touch(visit)
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
