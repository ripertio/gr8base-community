from django.urls import path

from . import views

app_name = "crags"

urlpatterns = [
    path("", views.crag_list, name="list"),
    path("new/", views.crag_create, name="create"),
    path("mine/", views.crag_mine, name="mine"),
    path("<int:pk>/", views.crag_detail, name="detail"),
    path("<int:pk>/edit/", views.crag_edit, name="edit"),
    path("<int:pk>/publish/", views.crag_publish, name="publish"),
    path("<int:pk>/return/", views.crag_return, name="return"),
    path("<int:pk>/delete/", views.crag_delete, name="delete"),
    path("<int:pk>/rate/", views.crag_rate, name="rate"),
    path("<int:pk>/comments/add/", views.comment_add, name="comment_add"),
    path("comments/<int:pk>/delete/", views.comment_delete, name="comment_delete"),
    path("<int:pk>/photos/add/", views.photo_add, name="photo_add"),
    path("photos/<int:pk>/delete/", views.photo_delete, name="photo_delete"),
]