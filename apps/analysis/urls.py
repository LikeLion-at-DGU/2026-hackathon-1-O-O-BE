from django.urls import path

from apps.analysis.views import VisitFinishView

urlpatterns = [
    path("visits/<str:visit_id>/finish", VisitFinishView.as_view(), name="visit-finish"),
]
