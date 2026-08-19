"""AI ① 컨텍스트 챗봇. 스트리밍 응답, 축 추출, 대화 적립."""

import json
import logging
from collections.abc import Iterator

from apps.analysis import recommend
from apps.analysis import taste as taste_module
from apps.analysis.taste import profile_of
from apps.chat import taste_map
from apps.chat.answers import AVOID_RATE
from apps.chat.context import build_messages
from apps.chat.models import ChatLog, Role
from apps.chat.wording import say
from apps.visits.models import Visit
from common.llm import LLMUnavailable, stream

logger = logging.getLogger(__name__)


def respond(visit: Visit, question: str, override: dict | None = None) -> Iterator[str]:
    """질문을 적립하고 답변을 SSE 조각으로 흘려보낸다.

    답변은 조각이 다 나온 뒤에 한 번에 저장한다. 조각마다 UPDATE를 치면 스트리밍
    도중 SQLite 쓰기 잠금이 걸린다.
    """
    ChatLog.objects.create(visit=visit, role=Role.USER, content=question)
    extracted = _absorb(visit, question)

    taste = taste_module.read(visit)
    candidates = recommend.suggest(visit, taste)
    messages = build_messages(visit, question, override, taste=taste, candidates=candidates)

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
    yield _sse(
        {
            "done": True,
            "message_id": answer.message_id,
            "recommendations": [item.as_dict() for item in candidates],
            "extracted": extracted,
            "profile_completion": taste_module.read(visit).confidence,
        }
    )


def _absorb(visit: Visit, question: str) -> dict:
    """발화에서 축을 뽑아 좌표에 반영한다.

    손님이 직접 말한 축은 `spoken`에 넣어 lock으로 취급한다. 부정은 회피율에
    가산한다 — 비율 체계에서 음수를 더할 자리가 회피율뿐이다.
    """
    preferred, rejected = taste_map.extract(question)
    if not preferred and not rejected:
        # 사전이 못 읽은 표현("무해한", "레트로한")만 LLM에 넘긴다. 흔한 말은 1차에서
        # 끝나므로 대부분의 발화에는 호출이 붙지 않는다. 답변 스트리밍 전에 부르는
        # 이유는 추출 결과가 이번 답변의 프롬프트에 들어가야 하기 때문이다.
        preferred, rejected = taste_map.llm_extract(question)
    if not preferred and not rejected:
        return {"axes": {}, "needs_confirm": False}

    profile = profile_of(visit)
    vector = dict(profile.vector)
    spoken = vector.setdefault("spoken", {})
    avoided = vector.setdefault("avoided", {})

    for axis, values in preferred.items():
        spoken[axis] = values[0]  # lock은 축 하나당 한 값이다
    for axis, values in rejected.items():
        for value in values:
            avoided.setdefault(axis, {})[value] = AVOID_RATE

    profile.vector = vector
    profile.save(update_fields=["vector", "updated_at"])

    return {
        "axes": {axis: values[0] for axis, values in preferred.items()},
        "rejected": {axis: values for axis, values in rejected.items()},
        "reading": _reading(preferred, rejected),
        "needs_confirm": bool(preferred),
    }


def _reading(preferred: dict[str, list[str]], rejected: dict[str, list[str]]) -> str:
    """되돌려 확인할 문장. "베이지 · 절제된 느낌으로 읽었어요"의 앞부분을 만든다.

    축 하나에 값이 여럿 올 수 있으므로(빨강도 핑크도 싫어) 리스트를 펼쳐서 읽는다.
    """
    parts = [say(values[0]) for values in preferred.values()]
    parts += [f"{say(value)} 제외" for values in rejected.values() for value in values]
    return " · ".join(parts)


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
