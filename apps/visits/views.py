from django.db import transaction
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from api.authentication import ANONYMOUS_UUID_HEADER
from apps.catalog.models import Store
from apps.catalog.repositories import get_default_store, scenes_with_products
from apps.catalog.serializers import SceneSerializer, StoreBriefSerializer
from apps.visits import services
from apps.visits.models import Visit, Visitor
from apps.visits.serializers import EnterRequestSerializer, EnterResponseSerializer


class EnterView(APIView):
    """POST /api/v1/enter — 입장. 사용자 API 중 유일하게 토큰 없이 호출한다."""

    authentication_classes = []
    permission_classes = [AllowAny]

    @extend_schema(
        request=EnterRequestSerializer,
        responses={200: EnterResponseSerializer},
        parameters=[
            OpenApiParameter(
                name="X-Anonymous-UUID",
                location=OpenApiParameter.HEADER,
                required=False,
                description="클라이언트가 보관하는 익명 UUID. 최초 진입 시에는 생략한다.",
            )
        ],
        auth=[],
        tags=["Visit"],
    )
    def post(self, request):
        serializer = EnterRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data

        store = get_default_store()
        visitor, is_new_visitor = services.resolve_or_issue(
            services.parse_uuid(request.META.get(ANONYMOUS_UUID_HEADER))
        )
        visit, resumed = self._resolve_visit(visitor, store, payload)

        body = {
            # 신규 발급이 아닐 때도 항상 내려준다. 클라이언트가 보낸 uuid가 만료·위조라
            # 서버가 새로 발급한 경우, 응답에 없으면 클라이언트는 자기 uuid가 여전히
            # 유효하다고 오해하고 죽은 값을 계속 보낸다.
            "anonymous_uuid": str(visitor.pk),
            "visit_id": visit.id,
            "visit_token": visit.token,
            "muse_no": visit.muse_no,
            "muse_label": visit.muse_label,
            "store": StoreBriefSerializer(store).data,
            "scenes": SceneSerializer(scenes_with_products(store), many=True).data,
            "is_new": is_new_visitor,
            "is_resumed": resumed,
        }
        if resumed:
            body["resumed_visit"] = services.summarize(visit)

        return Response(body, status=status.HTTP_200_OK)

    @transaction.atomic
    def _resolve_visit(self, visitor: Visitor, store: Store, payload: dict) -> tuple[Visit, bool]:
        """이어받을 Visit이 있으면 그것을, 없으면 새 Visit을 준다.

        이어할 때는 토큰까지 그대로 돌려주므로 클라이언트가 저장해 둔 토큰이 계속 유효하다.
        """
        resumable = services.find_resumable(visitor)

        if resumable is not None and not payload["force_new"]:
            services.touch(resumable)
            return resumable, True

        if resumable is not None:
            # "새로 시작"을 눌렀다. 방치가 아니라 사용자의 선택이므로 자동 종료로 세지 않는다.
            services.expire(resumable, auto_closed=False)

        visit = services.start(
            visitor,
            store,
            age_band=payload.get("age_band", ""),
            gender=payload.get("gender", ""),
        )
        return visit, False
