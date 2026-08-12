"""AI ① 컨텍스트 챗봇. 스트리밍 응답과 대화 적립을 담당한다."""

import json
import logging
from collections.abc import Iterator

from apps.chat.context import build_messages
from apps.chat.models import ChatLog, Role
from apps.visits.models import Visit
from common.llm import LLMUnavailable, stream

logger = logging.getLogger(__name__)


def respond(visit: Visit, question: str, override: dict | None = None) -> Iterator[str]:
    """질문을 적립하고 답변을 SSE 조각으로 흘려보낸다.

    답변은 조각이 다 나온 뒤에 한 번에 저장한다. 조각마다 UPDATE를 치면 SQLite
    쓰기 잠금이 스트리밍 도중에 걸린다.
    """
    ChatLog.objects.create(visit=visit, role=Role.USER, content=question)
    messages = build_messages(visit, question, override)

    chunks: list[str] = []
    try:
        for delta in stream(messages):
            chunks.append(delta)
            yield _sse({"delta": delta})
    except LLMUnavailable as error:
        # 스트림이 이미 시작됐으면 HTTP 상태를 바꿀 수 없다. 에러도 이벤트로 흘려보낸다.
        logger.warning("챗봇 응답 중단: %s", error.detail)
        yield _sse({"error": {"code": error.default_code, "message": str(error.detail)}})
        return

    answer = ChatLog.objects.create(
        visit=visit, role=Role.ASSISTANT, content="".join(chunks) or "답변을 생성하지 못했습니다."
    )
    yield _sse({"done": True, "message_id": answer.message_id, "recommendations": []})


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
