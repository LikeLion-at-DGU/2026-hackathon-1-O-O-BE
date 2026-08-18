"""식별자 생성. 명세의 v_9f8e / p_101 / r_7Ka9xQ 형식을 한 곳에서만 만든다."""

import secrets

_ID_BYTES = 8
_TOKEN_BYTES = 24  # visit_token
_SLUG_BYTES = 16  # 리포트 slug. 인증 없이 열리므로 짧게 만들면 열거 가능해진다


def gen_id(prefix: str) -> str:
    """접두어 붙은 공개 식별자. 예: gen_id("v") -> "v_Ka9xQ7Lm"."""
    return f"{prefix}_{secrets.token_urlsafe(_ID_BYTES)}"


def gen_visit_token() -> str:
    return secrets.token_urlsafe(_TOKEN_BYTES)


def gen_report_slug() -> str:
    return f"r_{secrets.token_urlsafe(_SLUG_BYTES)}"
