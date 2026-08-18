"""16유형 캐릭터 시드.

축 조합 16개를 빠짐없이 만들어 둔다. 유형이 하나라도 비면 그 코드를 받은 방문자의
리포트에서 가장 눈에 띄는 자리가 비게 된다.

이름·한 줄 설명·이미지는 기획이 채울 자리다. 여기서는 축 조합을 그대로 옮긴
**임시 문구**만 넣고, 이미 채워진 값은 덮어쓰지 않는다.
"""

from itertools import product

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.analysis.character import TASTE_AXES
from apps.analysis.models import Character

PLACEHOLDER_PREFIX = "[임시] "


class Command(BaseCommand):
    help = "16유형 캐릭터를 채운다 (여러 번 실행해도 기존 문구를 덮어쓰지 않는다)."

    @transaction.atomic
    def handle(self, *args, **options):
        created = 0
        for codes in product(*[(axis.positive_code, axis.negative_code) for axis in TASTE_AXES]):
            type_code = "".join(codes)
            _, is_new = Character.objects.get_or_create(
                type_code=type_code,
                defaults={
                    "name": PLACEHOLDER_PREFIX + _labels(codes),
                    "one_liner": f"{_labels(codes)} 취향을 가진 타입이에요.",
                },
            )
            created += is_new

        self.stdout.write(
            self.style.SUCCESS(f"캐릭터 16유형 확인 완료 (신규 {created}건, 기존 {16 - created}건 유지)")
        )
        if created:
            self.stdout.write("이름·한 줄 설명·이미지는 /django-admin/analysis/character/ 에서 교체한다.")


def _labels(codes: tuple[str, ...]) -> str:
    return " · ".join(axis.label_of(code) for axis, code in zip(TASTE_AXES, codes, strict=True))
