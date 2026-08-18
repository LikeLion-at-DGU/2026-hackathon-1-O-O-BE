from django.urls import path

from apps.visits.views import EnterView

urlpatterns = [
    path("enter", EnterView.as_view(), name="enter"),
]
