from django.urls import path

from . import change_requests, views

app_name = "crags"

urlpatterns = [
    path("", views.crag_list, name="list"),
    path("suggestions.json", views.crag_suggestions, name="suggestions"),
    path("new/", views.crag_create, name="create"),
    path("mine/", views.crag_mine, name="mine"),
    path("<int:pk>/", views.crag_detail, name="detail"),
    path("<int:pk>/edit/", views.crag_edit, name="edit"),
    path("<int:pk>/publish/", views.crag_publish, name="publish"),
    path("<int:pk>/return/", views.crag_return, name="return"),
    path("<int:pk>/reject/", views.crag_reject, name="reject"),
    path("<int:pk>/review/reply/", views.review_reply, name="review_reply"),
    path("<int:pk>/suggest/", change_requests.suggest, name="suggest"),
    path("changes/<int:pk>/", change_requests.change_request_detail, name="change_request"),
    path("changes/<int:pk>/reply/", change_requests.reply, name="change_request_reply"),
    path("changes/<int:pk>/close/", change_requests.close, name="change_request_close"),
    path("<int:pk>/delete/", views.crag_delete, name="delete"),
    path("<int:pk>/rate/", views.crag_rate, name="rate"),
    path("<int:pk>/comments/add/", views.comment_add, name="comment_add"),
    path("comments/<int:pk>/delete/", views.comment_delete, name="comment_delete"),
    path("<int:pk>/photos/add/", views.photo_add, name="photo_add"),
    path("photos/<int:pk>/delete/", views.photo_delete, name="photo_delete"),
]