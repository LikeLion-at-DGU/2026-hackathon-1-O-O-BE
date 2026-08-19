"""분석 파이프라인의 가중치 상수. 숫자를 코드 여기저기 흩뿌리지 않는다.

값은 `tasks/결정사항.md` §4-4·§4-5와 명세 ⑤단계(75/15/10)에서 왔다.
데모 데이터로 한 번 돌려보고 조정할 것을 전제로 한 값이다.
"""

# ② 관심도 — log 가중합. 한 상품을 30번 본 사람이 프로필을 지배하지 않게 한다.
WEIGHT_VIEW = 1.0  # 가장 약한 신호
WEIGHT_DWELL = 1.5  # 가장 중요한 신호 (오래 볼수록 관심이 크다)
WEIGHT_CHAT = 2.0  # 대화에서 언급된 상품
DWELL_UNIT_MS = 1000  # 체류시간을 초 단위로 환산해 log에 넣는다

# ③ confidence — 신호가 적을 때 틀린 개인화를 하지 않기 위한 억제 장치
CONFIDENCE_VIEW_WEIGHT = 0.40
CONFIDENCE_VIEW_TARGET = 8  # 상품 8개를 보면 만점
CONFIDENCE_DWELL_WEIGHT = 0.30
CONFIDENCE_DWELL_TARGET_MS = 240_000  # 4분
# 찜이 가져가던 0.10을 질문이 받았다. 셋의 합이 1.0이 아니면 confidence 상한이
# 그만큼 내려가 아무리 오래 관람해도 만점이 안 나온다. 의도가 분명한 행동이라는
# 성격이 가장 가까운 것이 질문이라 그쪽으로 옮겼다.
CONFIDENCE_QUESTION_WEIGHT = 0.30
CONFIDENCE_QUESTION_TARGET = 3
CONFIDENCE_EXPLORING = 0.35  # 미만이면 "탐색 중"으로 표시한다

# ④ 취향 벡터 — 대화에서 뽑은 선호/비선호를 행동 위에 얹는다
CHAT_PREFERENCE_BONUS = 0.5
CHAT_AVOID_PENALTY = 0.5

# ⑤ 스코어링
WEIGHT_PERSONAL = 0.75
WEIGHT_POPULAR = 0.15
WEIGHT_NEW = 0.10
DISCOVERY_BONUS = 0.05  # 이번에 안 본 상품에만. 추천이 이미 본 것으로만 차지 않게 한다

# ⑦ 리포트 구성 — 상품이 30개뿐이라 더 노출하면 추천이 아니라 목록이 된다
REPORT_RECOMMENDATION_COUNT = 8  # 히어로 1개 + 그리드 8개
REPORT_INTERESTED_COUNT = 5
REPORT_KEYWORD_COUNT = 3
