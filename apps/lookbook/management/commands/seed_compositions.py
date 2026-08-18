"""구도 4종 시드. 전 무드가 공용으로 쓰는 고정 마스터다.

레퍼런스 이미지와 프롬프트는 기획이 채울 자리라 비워 둔다. 값이 비어도 구도 선택은
동작하고, 채워지면 배포 없이 반영된다.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.lookbook.models import Composition

# 명세 "구도 선택" 표. 사진에 맞는 구도만 후보에 넣어야 왜곡이 안 생긴다.
COMPOSITIONS = [
    ("close_up", "클로즈업", 0.15, 1.00),
    ("half_body", "상반신", 0.05, 0.35),
    ("wide", "와이드", 0.00, 0.15),
    ("product_focus", "상품 중심", 0.00, 1.00),
]


class Command(BaseCommand):
    help = "화보 구도 4종을 채운다 (여러 번 실행해도 기존 값을 덮어쓰지 않는다)."

    @transaction.atomic
    def handle(self, *args, **options):
        created = 0
        for code, name, min_face, max_face in COMPOSITIONS:
            _, is_new = Composition.objects.get_or_create(
                code=code,
                defaults={"name": name, "min_face": min_face, "max_face": max_face},
            )
            created += is_new

        self.stdout.write(self.style.SUCCESS(f"구도 {len(COMPOSITIONS)}종 확인 완료 (신규 {created}건)"))
