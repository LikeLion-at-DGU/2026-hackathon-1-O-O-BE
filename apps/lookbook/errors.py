"""화보 전용 예외. 뷰와 서비스가 함께 쓰므로 순환 import를 피해 여기 모은다."""

from rest_framework import status
from rest_framework.exceptions import APIException


class ReportPending(APIException):
    """분석이 아직 안 끝났다. 잠시 뒤 다시 부르면 되는 상태라 409로 구분한다."""

    status_code = status.HTTP_409_CONFLICT
    default_code = "CONFLICT"
    default_detail = "report_pending"


class RegenerationLimit(APIException):
    """재생성 3회를 다 썼다. 이미지 생성은 호출당 비용이 붙어 무제한으로 열 수 없다."""

    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    default_code = "RATE_LIMITED"
    default_detail = "regeneration_limit"
