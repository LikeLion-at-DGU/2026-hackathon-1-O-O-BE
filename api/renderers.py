"""SSE 렌더러.

DRF는 뷰에 들어가기 전에 Accept 헤더와 렌더러를 맞춰본다(content negotiation).
text/event-stream을 받을 렌더러가 없으면 스트리밍 응답을 만들기도 전에 406이 난다.
Swagger UI가 이 Accept를 보내기 때문에 실제로 걸렸다.
"""

import json

from rest_framework.renderers import BaseRenderer


class EventStreamRenderer(BaseRenderer):
    """협상만 통과시키는 렌더러. 실제 본문은 StreamingHttpResponse가 직접 만든다.

    에러 응답(400·401·429 등)이 이 렌더러로 넘어올 수 있으므로 dict는 JSON으로 낸다.
    """

    media_type = "text/event-stream"
    format = "txt"
    charset = "utf-8"

    def render(self, data, accepted_media_type=None, renderer_context=None):
        if data is None:
            return ""
        if isinstance(data, str | bytes):
            return data
        return json.dumps(data, ensure_ascii=False)
