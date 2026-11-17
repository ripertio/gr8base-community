from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.shortcuts import render
from django.urls import include, path
from crags.views import crag_list, notification_list, notification_settings
from gr8base.views import (
    cookie_consent, doc_index, doc_page, healthz,
)


urlpatterns = [
    path("", crag_list, name="home"),
    path("", include("accounts.urls")),
    path("crags/", include("crags.urls")),
    path("moderation/", include("crags.moderation_urls")),
    path("notifications/", notification_list, name="notifications"),
    path("notifications/settings/", notification_settings, name="notification_settings"),
    path("stats/", include("stats.urls")),
    path("docs/", doc_index, name="docs"),
    path("docs/<slug:slug>/", doc_page, name="doc_page"),
    path("cookies/", cookie_consent, name="cookie_consent"),
    path("healthz/", healthz, name="healthz"),
    path("admin/", admin.site.urls),
    path("accounts/", include("allauth.urls")),
]


if settings.DEBUG:
    urlpatterns += static(
        settings.MEDIA_URL,
        document_root=settings.MEDIA_ROOT,
    )