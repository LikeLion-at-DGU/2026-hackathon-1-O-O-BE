from django.db import transaction
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from api.authentication import ANONYMOUS_UUID_HEADER
from apps.catalog.repositories import get_default_store, scenes_with_products
from apps.catalog.serializers import SceneSerializer, StoreBriefSerializer
from apps.visits import services
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
            "visit_id": visit.id,
            "visit_token": visit.token,
            "store": StoreBriefSerializer(store).data,
            "scenes": SceneSerializer(scenes_with_products(store), many=True).data,
            "resumed": resumed,
        }
        if is_new_visitor:
            body["anonymous_uuid"] = str(visitor.pk)
        if resumed:
            body["resumed_visit"] = services.summarize(visit)

        return Response(body, status=status.HTTP_200_OK)

    @transaction.atomic
    def _resolve_visit(self, visitor, store, payload) -> tuple:
        """이어받을 Visit이 있으면 그것을, 없으면 새 Visit을 준다.

        이어할 때는 토큰까지 그대로 돌려주므로 클라이언트가 저장해 둔 토큰이 계속 유효하다.
        """
        resumable = services.find_resumable(visitor)

        if resumable is not None and not payload["force_new"]:
            services.touch(resumable)
            return resumable, True

        if resumable is not None:
            services.expire(resumable)  # "새로 시작"을 눌렀다

        services.apply_demographics(visitor, payload.get("age_band", ""), payload.get("gender", ""))
        return services.start(visitor, store), False
