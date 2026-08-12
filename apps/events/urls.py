from django.urls import path

from apps.events.views import EventBatchView

urlpatterns = [
    path("events", EventBatchView.as_view(), name="events"),
]
