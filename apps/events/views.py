from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from api.permissions import IsOpenVisit
from apps.events.serializers import EventBatchResultSerializer, EventBatchSerializer
from apps.events.services import append_batch
from apps.visits.services import touch


class EventBatchView(APIView):
    """POST /api/v1/events — 행동 이벤트 배치 수집.

    클라이언트가 모아뒀다가 주기적으로, 또는 페이지를 떠날 때 보낸다.
    저장은 append-only이고 event_id로 중복을 제거하므로 재전송이 안전하다.
    """

    permission_classes = [IsOpenVisit]

    @extend_schema(
        request=EventBatchSerializer,
        responses={202: EventBatchResultSerializer},
        tags=["Event"],
    )
    def post(self, request):
        serializer = EventBatchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        visit = request.auth
        if serializer.validated_data["visit_id"] != visit.id:
            # 토큰이 가리키는 방문만 기록할 수 있다. 클라이언트가 보낸 visit_id를 믿지 않는다.
            raise PermissionDenied("다른 방문의 이벤트는 기록할 수 없습니다.")

        result = append_batch(visit, serializer.validated_data["events"])
        touch(visit)
        return Response(result, status=status.HTTP_202_ACCEPTED)
