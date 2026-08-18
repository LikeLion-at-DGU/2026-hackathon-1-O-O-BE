"""모든 에러를 {"error": {code, message, detail}} 하나의 형식으로 통일한다.

프론트가 엔드포인트마다 다른 에러 모양을 파싱하지 않게 하려고 존재한다.
"""

from rest_framework import status
from rest_framework.exceptions import APIException

# 상태코드별 기본 code. 예외가 자체 code(UPPER_SNAKE)를 갖고 있으면 그게 우선한다.
DEFAULT_CODES = {
    status.HTTP_400_BAD_REQUEST: "VALIDATION_ERROR",
    status.HTTP_401_UNAUTHORIZED: "UNAUTHORIZED",
    status.HTTP_403_FORBIDDEN: "FORBIDDEN",
    status.HTTP_404_NOT_FOUND: "NOT_FOUND",
    status.HTTP_405_METHOD_NOT_ALLOWED: "METHOD_NOT_ALLOWED",
    status.HTTP_406_NOT_ACCEPTABLE: "NOT_ACCEPTABLE",
    status.HTTP_409_CONFLICT: "CONFLICT",
    status.HTTP_429_TOO_MANY_REQUESTS: "RATE_LIMITED",
}

FALLBACK_MESSAGES = {
    status.HTTP_400_BAD_REQUEST: "입력값이 올바르지 않습니다.",
    status.HTTP_401_UNAUTHORIZED: "인증 정보가 올바르지 않습니다.",
    status.HTTP_403_FORBIDDEN: "권한이 없습니다.",
    status.HTTP_404_NOT_FOUND: "요청한 리소스를 찾을 수 없습니다.",
    status.HTTP_406_NOT_ACCEPTABLE: "요청한 응답 형식을 지원하지 않습니다.",
    status.HTTP_429_TOO_MANY_REQUESTS: "요청이 너무 많습니다. 잠시 후 다시 시도해주세요.",
}


class Unauthorized(APIException):
    """401을 그대로 내려주기 위한 예외.

    DRF의 AuthenticationFailed를 쓰면 WWW-Authenticate 헤더가 없을 때 401을 403으로
    바꿔버린다. 명세가 관리자 인증 실패를 401 UNAUTHORIZED로 정의했으므로 직접 만든다.
    """

    status_code = status.HTTP_401_UNAUTHORIZED
    default_code = "UNAUTHORIZED"
    default_detail = "인증 정보가 올바르지 않습니다."


class InvalidVisitToken(APIException):
    status_code = status.HTTP_401_UNAUTHORIZED
    default_code = "INVALID_VISIT_TOKEN"
    default_detail = "유효하지 않거나 만료된 visit token 입니다."


def oando_exception_handler(exc, context):
    # rest_framework.views가 이 모듈을 로드하는 시점에 아직 초기화되지 않으므로
    # (인증 클래스 → api.exceptions → rest_framework.views 순환) 함수 안에서 가져온다.
    from rest_framework.views import exception_handler

    response = exception_handler(exc, context)
    if response is None:
        return None  # 처리되지 않은 예외는 Django가 500으로 넘긴다 (삼키지 않는다)

    response.data = {
        "error": {
            "code": _code_of(exc, response.status_code),
            "message": _message_of(exc, response.status_code),
            "detail": _detail_of(response.data),
        }
    }
    return response


def _code_of(exc, status_code: int) -> str:
    """직접 정의한 UPPER_SNAKE code만 신뢰하고, DRF 기본값은 상태코드로 매핑한다."""
    code = getattr(exc, "default_code", None)
    if isinstance(code, str) and code.isupper():
        return code
    return DEFAULT_CODES.get(status_code, "INTERNAL_ERROR")


def _message_of(exc, status_code: int) -> str:
    detail = getattr(exc, "detail", None)
    if isinstance(detail, str):
        return detail
    return FALLBACK_MESSAGES.get(status_code, "요청을 처리할 수 없습니다.")


def _detail_of(data):
    """필드 검증 실패처럼 항목별 설명이 있을 때만 detail을 채운다."""
    return data if isinstance(data, dict) and "detail" not in data else None


def json_not_found(request, exception):
    """URL 자체가 매칭되지 않은 경우. DRF를 타지 않으므로 여기서 같은 형식으로 맞춘다."""
    from django.http import JsonResponse

    return JsonResponse(
        {"error": {"code": "NOT_FOUND", "message": "요청한 경로를 찾을 수 없습니다.", "detail": None}},
        status=status.HTTP_404_NOT_FOUND,
        json_dumps_params={"ensure_ascii": False},
    )


def json_server_error(request):
    from django.http import JsonResponse

    return JsonResponse(
        {"error": {"code": "INTERNAL_ERROR", "message": "서버 오류가 발생했습니다.", "detail": None}},
        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        json_dumps_params={"ensure_ascii": False},
    )
