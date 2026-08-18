"""Visit.created_at 추가.

auto_now_add 필드는 새로 저장되는 행에만 값을 넣어주므로, 이미 있는 행을 채울
값이 필요하다. 그래서 이 마이그레이션에서만 timezone.now를 기본값으로 쓰고
(preserve_default=False) 이후 저장부터는 모델의 auto_now_add가 담당한다.
"""

import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("visits", "0002_remove_visit_created_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="visit",
            name="created_at",
            field=models.DateTimeField(auto_now_add=True, default=django.utils.timezone.now),
            preserve_default=False,
        ),
    ]
