"""취향 벡터의 키 규칙. 벡터를 만드는 쪽과 읽는 쪽이 같은 문자열을 써야 한다.

`{축}:{값}` 형태로 둔 이유는 벡터가 JSON 컬럼에 그대로 박제되기 때문이다.
중첩 dict보다 평평한 키가 저장·비교·디버깅 모두 쉽다.
"""

SEPARATOR = ":"


def axis_value_key(axis: str, value: str) -> str:
    """예: axis_value_key("color", "black") -> "color:black"."""
    return f"{axis}{SEPARATOR}{value}"


def split_key(key: str) -> tuple[str, str]:
    axis, _, value = key.partition(SEPARATOR)
    return axis, value
