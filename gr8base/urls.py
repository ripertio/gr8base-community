from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.shortcuts import render
from django.urls import include, path
from crags.views import crag_list
from gr8base.views import doc_index, doc_page


urlpatterns = [
    path("", crag_list, name="home"),
    path("crags/", include("crags.urls")),
    path("docs/", doc_index, name="docs"),
    path("docs/<slug:slug>/", doc_page, name="doc_page"),
    path("admin/", admin.site.urls),
    path("accounts/", include("allauth.urls")),
]


if settings.DEBUG:
    urlpatterns += static(
        settings.MEDIA_URL,
        document_root=settings.MEDIA_ROOT,
    )