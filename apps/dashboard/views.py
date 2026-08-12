from django.conf import settings
from django.contrib.auth import authenticate
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import AccessToken

from api.exceptions import Unauthorized
from apps.dashboard.serializers import AdminAuthResponseSerializer, AdminAuthSerializer


class AdminAuthThrottle(AnonRateThrottle):
    """무차별 대입 방지. 관리자 로그인만 대상이다."""

    rate = "10/min"


class AdminAuthView(APIView):
    """POST /api/v1/admin/auth — /admin/* 호출에 필요한 Bearer 토큰을 발급한다.

    사용자 API와 완전히 별개다. 사용자는 여전히 로그인하지 않는다.
    """

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [AdminAuthThrottle]

    @extend_schema(
        request=AdminAuthSerializer,
        responses={200: AdminAuthResponseSerializer},
        auth=[],
        tags=["Admin"],
    )
    def post(self, request):
        serializer = AdminAuthSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # 이메일을 username으로 쓴다. 관리자는 createsuperuser로만 만든다.
        user = authenticate(
            request,
            username=serializer.validated_data["email"],
            password=serializer.validated_data["password"],
        )
        if user is None or not user.is_staff:
            raise Unauthorized("관리자 자격 증명이 일치하지 않습니다.")

        token = AccessToken.for_user(user)
        return Response(
            {
                "access_token": str(token),
                "expires_in": int(settings.SIMPLE_JWT["ACCESS_TOKEN_LIFETIME"].total_seconds()),
                "store_ids": [settings.DEFAULT_STORE_ID],
            },
            status=status.HTTP_200_OK,
        )
