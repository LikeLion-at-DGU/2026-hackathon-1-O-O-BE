"""OpenAI 게이트웨이. 모델 교체·재시도·사용량 로깅을 이 파일 한 곳에서 통제한다.

키는 환경변수에서만 읽고, 앱 코드는 OpenAI SDK를 직접 import하지 않는다.
"""

import logging
from collections.abc import Iterator

from django.conf import settings
from openai import OpenAI, OpenAIError
from rest_framework.exceptions import APIException

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT_SECONDS = 20
MAX_OUTPUT_TOKENS = 400


class LLMUnavailable(APIException):
    status_code = 503
    default_code = "LLM_UNAVAILABLE"
    default_detail = "AI 응답을 생성할 수 없습니다. 잠시 후 다시 시도해주세요."


def _client() -> OpenAI:
    if not settings.OPENAI_API_KEY:
        # 데모 중 조용히 실패하지 않도록 원인을 분명히 말한다.
        raise LLMUnavailable("OPENAI_API_KEY가 설정되지 않았습니다. .env를 확인하세요.")
    return OpenAI(api_key=settings.OPENAI_API_KEY, timeout=REQUEST_TIMEOUT_SECONDS)


def stream(messages: list[dict]) -> Iterator[str]:
    """응답을 조각(delta) 단위로 흘려보낸다. 첫 글자가 빨리 떠야 기다리는 느낌이 준다."""
    try:
        response = _client().chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=messages,
            max_tokens=MAX_OUTPUT_TOKENS,
            stream=True,
        )
        for chunk in response:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta
    except OpenAIError as error:
        logger.exception("LLM 스트리밍 실패: %s", error)
        raise LLMUnavailable() from error
