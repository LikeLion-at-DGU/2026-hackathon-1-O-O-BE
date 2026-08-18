from django.urls import path

from apps.lookbook.views import LookbookCandidateView, LookbookJobView, UploadPresignView

urlpatterns = [
    path(
        "reports/<str:slug>/lookbook/candidates",
        LookbookCandidateView.as_view(),
        name="lookbook-candidates",
    ),
    path("lookbooks/jobs/<str:job_id>", LookbookJobView.as_view(), name="lookbook-job"),
    path("uploads/presign", UploadPresignView.as_view(), name="upload-presign"),
]
