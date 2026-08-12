from django.urls import path

from apps.chat.views import ChatMessagesView, ChatView

urlpatterns = [
    path("chat/messages", ChatMessagesView.as_view(), name="chat-messages"),
    path("chat", ChatView.as_view(), name="chat"),
]
