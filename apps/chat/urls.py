from django.urls import path

from apps.chat.views import ChatMessagesView

urlpatterns = [
    path("chat/messages", ChatMessagesView.as_view(), name="chat-messages"),
]
