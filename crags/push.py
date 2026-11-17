"""Web Push: notifications and the number badge on the app icon.

Only active with both VAPID keys set (settings.PUSH_ENABLED). A device is
turned on in the notification settings (static/js/push.js); from then on each
notification type whose "On my phone" channel is on sends an encrypted push
message to it. The service worker (templates/sw.js) shows it as a quiet
notification and sets the badge to the user's open count, the same number as
on the burger icon (unread notifications plus open moderation tasks).
"""
import json
import logging

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import Notification, PushSubscription
from .notifications import can_moderate, wants

logger = logging.getLogger(__name__)

TITLE = "gr8base"


def vapid_subject():
    """The contact sent to push services; they accept only https:// or mailto:."""
    subject = settings.VAPID_SUBJECT
    if subject.startswith(("https://", "mailto:")):
        return subject
    return "mailto:hello@gr8base.com"  # e.g. dev, where SITE_URL is http://localhost


def badge_count(user):
    """The number on the app icon: what the burger icon shows."""
    from .moderation import open_task_count

    count = Notification.unread_for(user).count()
    if can_moderate(user) and wants(user, "REVIEW_WAITING", "in_app"):
        count += open_task_count()
    return count


def send_push(user, body, url, key):
    """Push body to every device of user, if they want key "On my phone". Never raises.

    url is a path on this site; the notification opens it when tapped.
    """
    try:
        if not settings.PUSH_ENABLED or user is None or not user.is_active:
            return
        if not wants(user, key, "push"):
            return
        devices = list(user.push_subscriptions.all())
        if not devices:
            return
        from pywebpush import WebPushException, webpush

        payload = json.dumps(
            {"title": TITLE, "body": body, "url": url, "badge": badge_count(user)}
        )
        for device in devices:
            try:
                webpush(
                    subscription_info={
                        "endpoint": device.endpoint,
                        "keys": {"p256dh": device.p256dh, "auth": device.auth},
                    },
                    data=payload,
                    vapid_private_key=settings.VAPID_PRIVATE_KEY,
                    vapid_claims={"sub": vapid_subject()},
                    ttl=24 * 3600,
                    timeout=5,
                )
                PushSubscription.objects.filter(pk=device.pk).update(last_success_at=timezone.now())
            except WebPushException as exc:
                status = getattr(exc.response, "status_code", None)
                if status in (404, 410):  # the device unsubscribed or the address expired
                    device.delete()
                    logger.info("push device removed user=%s (gone)", user.pk)
                else:
                    logger.warning("push failed user=%s status=%s", user.pk, status)
            except Exception:
                # one broken device must not stop the others
                logger.exception("push failed user=%s device=%s", user.pk, device.pk)
    except Exception:
        logger.exception("push failed user=%s", getattr(user, "pk", None))


def notify_push(user, kind, crag, actor=None, count=1, change_request=None):
    """Push the same text as the in-app notification. Never raises."""
    if user is None or (actor is not None and actor.pk == user.pk):
        return
    # an unsaved Notification only to build the text and link
    notice = Notification(
        user=user, kind=kind, crag=crag, actor=actor, count=count, change_request=change_request
    )
    try:
        body, url = notice.text, notice.url
    except Exception:
        logger.exception("push text failed kind=%s", kind)
        return
    send_push(user, body, url, kind)


def notify_moderators_push(crag, actor=None):
    """A crag waits for review: push to moderators who want it. Never raises."""
    from django.urls import reverse

    from .notifications import moderator_users

    if not settings.PUSH_ENABLED:
        return
    try:
        moderators = moderator_users().filter(push_subscriptions__isnull=False).distinct()
        if actor is not None:
            moderators = moderators.exclude(pk=actor.pk)
        for user in moderators:
            send_push(
                user, f"\u201c{crag.name}\u201d is waiting for review.",
                reverse("moderation:queue"), "REVIEW_WAITING",
            )
    except Exception:
        logger.exception("moderator push failed crag=%s", crag.pk)


# --- views --------------------------------------------------------------------


def service_worker(request):
    """The push service worker (templates/sw.js), at the site root to cover all pages."""
    if not settings.PUSH_ENABLED:
        raise Http404
    response = render(request, "sw.js", content_type="application/javascript")
    response["Cache-Control"] = "no-cache"  # browsers check for a new version on every visit
    return response


def _endpoint(data):
    endpoint = data.get("endpoint") if isinstance(data, dict) else None
    if not isinstance(endpoint, str) or not endpoint.startswith("https://") or len(endpoint) > 1000:
        return None
    return endpoint


@login_required
@require_POST
def subscribe(request):
    """Turn this device on: store its push address and keys."""
    if not settings.PUSH_ENABLED:
        raise Http404
    try:
        data = json.loads(request.body)
        keys = data["keys"]
        p256dh, auth = str(keys["p256dh"]), str(keys["auth"])
    except (ValueError, KeyError, TypeError):
        return JsonResponse({"error": "invalid subscription"}, status=400)
    endpoint = _endpoint(data)
    if endpoint is None or not p256dh or not auth or len(p256dh) > 200 or len(auth) > 100:
        return JsonResponse({"error": "invalid subscription"}, status=400)
    # a device belongs to whoever turned it on last (e.g. a shared tablet)
    PushSubscription.objects.update_or_create(
        endpoint=endpoint, defaults={"user": request.user, "p256dh": p256dh, "auth": auth}
    )
    logger.info("push device added user=%s", request.user.pk)
    return JsonResponse({"ok": True, "badge": badge_count(request.user)})


@login_required
@require_POST
def unsubscribe(request):
    """Turn this device off (also used when signing out on it)."""
    if not settings.PUSH_ENABLED:
        raise Http404
    try:
        endpoint = _endpoint(json.loads(request.body))
    except ValueError:
        endpoint = None
    if endpoint is None:
        return JsonResponse({"error": "invalid subscription"}, status=400)
    deleted, _ = PushSubscription.objects.filter(endpoint=endpoint, user=request.user).delete()
    if deleted:
        logger.info("push device removed user=%s", request.user.pk)
    return HttpResponse(status=204)
