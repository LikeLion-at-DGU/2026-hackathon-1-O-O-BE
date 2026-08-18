from django.apps import AppConfig
from django.core.checks import Error, register


class AnalysisConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.analysis"

    def ready(self) -> None:
        register(check_camp_coverage)


def check_camp_coverage(app_configs, **kwargs) -> list[Error]:
    """축 값이 진영에서 빠지면 그 값을 고른 손님이 조용히 반대편으로 분류된다.

    에러 없이 결과만 틀리는 종류라 기동 시 잡는다.
    """
    from apps.analysis.taste import missing_camp_values

    return [
        Error(
            f"{axis} 축의 값이 어느 진영에도 없습니다: {', '.join(values)}",
            hint="apps/analysis/taste.py의 CAMPS에 추가하세요.",
            id="analysis.E001",
        )
        for axis, values in missing_camp_values().items()
    ]
