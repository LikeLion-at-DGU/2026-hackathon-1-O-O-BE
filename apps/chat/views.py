from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from api.permissions import IsOpenVisit, IsVisitAuthenticated
from apps.chat import messages as timeline_service
from apps.chat.serializers import (
    ActionMessageSerializer,
    ChatMessageSerializer,
    TimelineSerializer,
)
from apps.visits.models import Visit


def assert_own_visit(request, visit_id: str) -> Visit:
    """토큰이 가리키는 방문만 다룰 수 있다. 클라이언트가 보낸 visit_id를 믿지 않는다."""
    visit = request.auth
    if visit_id != visit.id:
        raise PermissionDenied("다른 방문의 대화는 다룰 수 없습니다.")
    return visit


class ChatMessagesView(APIView):
    """/api/v1/chat/messages — 클릭 적립(POST)과 타임라인 복원(GET).

    POST: 진열대·상품 클릭이 직전과 같으면 말풍선을 새로 쌓지 않고 200으로 기존
    메시지를 돌려준다. 조회 횟수 같은 수치는 POST /events가 따로 남긴다.
    GET: 화면을 이동하거나 이어하기로 돌아와도 이 호출 하나로 타임라인이 복원된다.

    쓰기는 진행 중인 관람만, 읽기는 종료된 관람도 허용한다.
    """

    def get_permissions(self):
        return [IsOpenVisit()] if self.request.method == "POST" else [IsVisitAuthenticated()]

    @extend_schema(
        request=ActionMessageSerializer,
        responses={201: ChatMessageSerializer, 200: ChatMessageSerializer},
        tags=["Chat"],
    )
    def post(self, request):
        serializer = ActionMessageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data
        visit = assert_own_visit(request, payload["visit_id"])

        message, created = timeline_service.append_action(
            visit,
            payload["type"],
            scene=payload["scene"],
            product=payload["product"],
            preset_key=payload["preset_key"] or "",
        )
        code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        return Response(ChatMessageSerializer(message).data, status=code)

    @extend_schema(
        parameters=[
            OpenApiParameter(name="visit_id", required=True, description="대상 방문"),
        ],
        responses={200: TimelineSerializer},
        tags=["Chat"],
    )
    def get(self, request):
        visit = assert_own_visit(request, request.query_params.get("visit_id", ""))
        return Response(
            {
                "messages": ChatMessageSerializer(timeline_service.timeline(visit), many=True).data,
                "current_context": timeline_service.current_context(visit),
            }
        )
