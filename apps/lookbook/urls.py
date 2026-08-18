from django.urls import path

from apps.lookbook.views import (
    LookbookCandidateView,
    LookbookCreateView,
    LookbookDetailView,
    LookbookJobView,
    UploadPresignView,
)

urlpatterns = [
    path(
        "reports/<str:slug>/lookbook/candidates",
        LookbookCandidateView.as_view(),
        name="lookbook-candidates",
    ),
    path("lookbooks/jobs/<str:job_id>", LookbookJobView.as_view(), name="lookbook-job"),
    path("reports/<str:slug>/lookbook", LookbookCreateView.as_view(), name="lookbook-create"),
    path("lookbooks/<str:share_slug>", LookbookDetailView.as_view(), name="lookbook-detail"),
    path("uploads/presign", UploadPresignView.as_view(), name="upload-presign"),
]
