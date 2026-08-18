from django.conf import settings
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.exceptions import APIException, NotFound, PermissionDenied
from rest_framework.generics import get_object_or_404
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from api.permissions import IsVisitAuthenticated
from apps.analysis.models import Report, ReportStatus
from apps.lookbook import candidates, jobs, mocks, storage
from apps.lookbook.serializers import (
    CandidateListSerializer,
    JobStatusSerializer,
    PresignRequestSerializer,
    PresignResponseSerializer,
)


class ReportPending(APIException):
    """분석이 아직 안 끝났다. 잠시 뒤 다시 부르면 되는 상태라 409로 구분한다."""

    status_code = status.HTTP_409_CONFLICT
    default_code = "CONFLICT"
    default_detail = "report_pending"


class LookbookCandidateView(APIView):
    """GET /api/v1/reports/{slug}/lookbook/candidates — 화보에 담을 상품 후보 6개.

    화보는 관람이 끝난 뒤(`/finish` 이후) 열리는 화면이라 종료된 방문에서도
    호출된다. 그래서 IsOpenVisit이 아니라 IsVisitAuthenticated를 쓴다.
    """

    permission_classes = [IsVisitAuthenticated]

    @extend_schema(responses={200: CandidateListSerializer}, tags=["Lookbook"])
    def get(self, request, slug: str):
        report = get_object_or_404(Report.objects.select_related("visit"), pk=slug)
        self._assert_owns(request.auth, report)
        self._assert_ready(report)
        return Response(candidates.build(report), status=status.HTTP_200_OK)

    def _assert_owns(self, visit, report: Report) -> None:
        """slug는 추측하기 어렵지만 열쇠를 두 개 요구한다. 남의 리포트로 후보를 뽑지 못한다."""
        if report.visit_id != visit.id:
            raise PermissionDenied("이 리포트의 방문이 아닙니다.")

    def _assert_ready(self, report: Report) -> None:
        if report.status == ReportStatus.READY:
            return
        if report.status == ReportStatus.PENDING:
            raise ReportPending()
        raise NotFound("리포트 분석에 실패해 후보를 만들 수 없습니다.")


class LookbookJobView(APIView):
    """GET /api/v1/lookbooks/jobs/{job_id} — 화보 생성 진행 상태 (폴링).

    **인증이 없다.** job_id는 추측하기 어려운 값이고, 로딩 화면은 토큰이 만료된
    뒤에도 열려 있을 수 있다. 여기서 나가는 정보는 진행률뿐이라 잃을 게 없다.

    **DB에 가지 않는다.** 화보 하나당 폴링이 8~9번이라 동시 100명이면 초당 33회가
    전부 똑같은 답을 가져오게 된다. 휘발성 값은 캐시에서 읽는다.
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    @extend_schema(responses={200: JobStatusSerializer}, auth=[], tags=["Lookbook"])
    def get(self, request, job_id: str):
        state = mocks.apply(job_id, jobs.read(job_id))
        if state is None:
            raise NotFound("진행 상태를 찾을 수 없습니다. 만료되었거나 없는 작업입니다.")
        return Response(jobs.as_response(state), status=status.HTTP_200_OK)


class UploadPresignView(APIView):
    """POST /api/v1/uploads/presign — 사진·마스크 업로드 URL 2개를 한 번에 발급한다.

    마스크는 인물 실루엣이다. 화보 생성 때 그 영역을 건드리지 않아야 체형과 얼굴이
    보존되므로, 사진과 짝으로 올릴 자리를 함께 내준다.
    """

    permission_classes = [IsVisitAuthenticated]

    @extend_schema(
        request=PresignRequestSerializer,
        responses={200: PresignResponseSerializer},
        tags=["Lookbook"],
    )
    def post(self, request):
        serializer = PresignRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        content_type = serializer.validated_data["content_type"]

        photo = storage.presign_put(storage.new_photo_key(content_type), content_type)
        mask = storage.presign_put(storage.mask_key_for(photo.key), storage.MASK_CONTENT_TYPE)

        return Response(
            {
                "photo_key": photo.key,
                "photo_upload_url": photo.upload_url,
                "mask_key": mask.key,
                "mask_upload_url": mask.upload_url,
                "headers": {
                    "photo": {"Content-Type": photo.content_type},
                    "mask": {"Content-Type": mask.content_type},
                },
                "expires_in": settings.UPLOAD_URL_TTL_SEC,
            },
            status=status.HTTP_200_OK,
        )
