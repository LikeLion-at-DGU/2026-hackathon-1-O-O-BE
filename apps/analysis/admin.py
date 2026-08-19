"""리포트 확인용 관리 화면."""

from django.contrib import admin

from apps.analysis.models import Report


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    """리포트는 박제물이라 읽기 전용이다. 실패한 방문을 찾는 용도로만 쓴다."""

    list_display = ("slug", "visit", "status", "created_at")
    list_filter = ("status",)
    readonly_fields = ("slug", "visit", "status", "payload", "failure_reason")
    list_select_related = ("visit",)
