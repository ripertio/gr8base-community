from django.urls import path

from . import moderation

app_name = "moderation"

urlpatterns = [
    path("", moderation.queue, name="queue"),
]
