"""구도 선택. 얼굴 비율로 후보를 좁히고 seed로 그중 하나를 고른다.

`seed`를 쓰는 이유는 **첫 컷이 사람마다 다르되 그 사람에겐 항상 같아야** 하기
때문이다. 모두가 같은 구도로 시작하면 공유된 화보가 다 비슷해 보인다.
"""

import hashlib
import secrets

FIRST_ATTEMPT = 1


def seed_for(visit_id: str, attempt: int) -> int:
    """첫 컷은 방문에서 파생된 고정값, 재생성은 난수.

    첫 컷의 랜덤 요소마저 그 사람 고유값에서 나오니 개인화의 연장이고, 같은 방문을
    다시 계산해도 같은 그림이 나와 결과를 되짚을 수 있다.
    """
    if attempt == FIRST_ATTEMPT:
        digest = hashlib.sha256(visit_id.encode()).digest()
        return int.from_bytes(digest[:4], "big")
    return secrets.randbits(32)


def choose(compositions: list, face_ratio: float | None, seed: int, used_codes: tuple[str, ...] = ()):
    """사진에 맞는 구도만 후보에 넣고 seed로 고른다. 이미 쓴 구도는 뒤로 미룬다.

    재생성인데 같은 구도가 다시 나오면 "다시 돌린" 티가 안 난다. 다만 후보가 그것뿐이면
    어쩔 수 없이 다시 쓴다 — 구도가 없어서 생성을 못 하는 것보다 낫다.
    """
    fitting = [item for item in compositions if item.accepts(face_ratio)]
    if not fitting:
        fitting = list(compositions)
    if not fitting:
        return None

    fresh = [item for item in fitting if item.code not in used_codes]
    pool = sorted(fresh or fitting, key=lambda item: item.code)
    return pool[seed % len(pool)]
