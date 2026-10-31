from django.urls import path

from . import views

app_name = "profiles"

urlpatterns = [
    path("profile/edit/", views.profile_edit, name="edit"),
    path("users/<str:username>/", views.profile_detail, name="detail"),
]
