import logging
from dataclasses import dataclass

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail, send_mass_mail
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

logger = logging.getLogger(__name__)

CHANNELS = ("in_app", "email")


@dataclass(frozen=True)
class NotificationType:
    """A row in the notification settings; in_app/email are the defaults."""

    key: str  # same as Notification.Kind where there is one
    label: str
    in_app: bool
    email: bool
    moderators_only: bool = False


# Defaults keep the behaviour from before the settings existed.
NOTIFICATION_TYPES = (
    NotificationType("COMMENT", "Someone comments on one of my crags", True, False),
    NotificationType("RATING", "Someone rates one of my crags", True, False),
    NotificationType("PHOTO", "Someone adds photos to one of my crags", True, False),
    NotificationType("PUBLISHED", "My crag is published", True, True),
    NotificationType("CHANGES_REQUESTED", "Changes are requested for my crag", True, True),
    # in the app: the counter next to "Moderation"
    NotificationType("REVIEW_WAITING", "A crag is waiting for review", True, True, moderators_only=True),
)
TYPES = {kind.key: kind for kind in NOTIFICATION_TYPES}


def can_moderate(user):
    """Who sees the moderation page (and its notifications)."""
    return user.is_staff or user.has_perm("crags.can_publish_crag")


def wants(user, key, channel):
    """Whether user gets notification type key on channel ("in_app" or "email")."""
    saved = (getattr(user, "notification_settings", None) or {}).get(key) or {}
    value = saved.get(channel)
    return getattr(TYPES[key], channel) if value is None else bool(value)


def types_for(user):
    """The settings rows this user sees (moderator rows only for moderators)."""
    return [kind for kind in NOTIFICATION_TYPES if not kind.moderators_only or can_moderate(user)]


def notify_submitter(crag):
    """Mail the submitter about a publish or return. Never raises."""
    from .models import Crag

    try:
        user = crag.created_by
        if user is None or not user.email:
            return
        kind = "PUBLISHED" if crag.status == Crag.Status.PUBLISHED else "CHANGES_REQUESTED"
        if not wants(user, kind, "email"):
            return
        link = settings.SITE_URL + reverse("crags:detail", args=[crag.pk])
        if crag.status == Crag.Status.PUBLISHED:
            subject = f"Your crag \"{crag.name}\" is published"
            outcome = "Published. Thank you for contributing!"
            reason = ""
        elif crag.status == Crag.Status.NEEDS_CHANGES:
            subject = f"Changes requested for your crag \"{crag.name}\""
            outcome = "Changes requested. Please edit the crag and submit it for review again."
            reason = crag.review_reason
        else:
            return
        lines = [f"Crag: {crag.name}", f"Outcome: {outcome}"]
        if reason:
            lines.append(f"Reason: {reason}")
        lines += ["", f"Open the crag: {link}", "", "gr8base community"]
        send_mail(subject, "\n".join(lines), None, [user.email])
        logger.info("review mail sent crag=%s user=%s status=%s", crag.pk, user.pk, crag.status)
    except Exception:
        logger.exception("review mail failed crag=%s", crag.pk)


def notify_moderators(crag, actor=None):
    """Mail everyone who may publish that a crag waits for review. Never raises.

    Recipients: active users with an e-mail address and the publish permission
    (superusers and Crag Managers), except the person who just submitted. Each gets
    their own message, so addresses are not shared.
    """
    try:
        User = get_user_model()
        recipients = (
            User.objects.filter(is_active=True)
            .filter(
                Q(is_superuser=True)
                | Q(
                    groups__permissions__content_type__app_label="crags",
                    groups__permissions__codename="can_publish_crag",
                )
                | Q(
                    user_permissions__content_type__app_label="crags",
                    user_permissions__codename="can_publish_crag",
                )
            )
            .exclude(email="")
            .distinct()
        )
        if actor is not None:
            recipients = recipients.exclude(pk=actor.pk)
        emails = [user.email for user in recipients if wants(user, "REVIEW_WAITING", "email")]
        if not emails:
            logger.info("moderator mail skipped crag=%s: no recipients", crag.pk)
            return
        link = settings.SITE_URL + reverse("moderation:queue")
        submitter = crag.created_by.username if crag.created_by else "unknown"
        subject = f"Crag waiting for review: \"{crag.name}\""
        body = "\n".join(
            [
                f"Crag: {crag.name}",
                f"Area: {crag.area.name}",
                f"Submitted by: {submitter}",
                "",
                f"Open the moderation page: {link}",
                "",
                "gr8base community",
            ]
        )
        send_mass_mail([(subject, body, None, [email]) for email in emails])
        logger.info("moderator mail sent crag=%s recipients=%s", crag.pk, len(emails))
    except Exception:
        logger.exception("moderator mail failed crag=%s", crag.pk)


def notify_in_app(user, kind, crag, actor=None, count=1):
    """Add an in-app notification for user about their crag. Never raises.

    Nothing is created for your own actions or for inactive accounts. Repeated
    ratings and photo uploads by the same person are merged into the unread
    notification that is already there, instead of piling up.
    """
    from .models import Notification

    try:
        if user is None or not user.is_active or (actor is not None and actor.pk == user.pk):
            return
        if not wants(user, kind, "in_app"):
            return
        if kind in (Notification.Kind.RATING, Notification.Kind.PHOTO):
            existing = Notification.objects.filter(
                user=user, kind=kind, crag=crag, actor=actor, read_at__isnull=True
            ).first()
            if existing is not None:
                if kind == Notification.Kind.PHOTO:
                    existing.count = min(existing.count + count, 32767)
                existing.created_at = timezone.now()
                existing.save(update_fields=["count", "created_at"])
                return
        Notification.objects.create(user=user, kind=kind, crag=crag, actor=actor, count=count)
    except Exception:
        logger.exception("notification failed crag=%s kind=%s", crag.pk, kind)


def email_owner(user, kind, crag, actor=None, count=1):
    """Mail the crag's creator about a comment, rating or photos, if they want it.

    Off by default (see NOTIFICATION_TYPES). Never raises.
    """
    from .models import Notification

    try:
        if user is None or not user.is_active or not user.email:
            return
        if actor is not None and actor.pk == user.pk:
            return
        if not wants(user, kind, "email"):
            return
        # an unsaved Notification only to build the same text as in the app
        notice = Notification(user=user, kind=kind, crag=crag, actor=actor, count=count)
        subject = f"{Notification.Kind(kind).label}: \u201c{crag.name}\u201d"
        body = "\n".join([
            notice.text,
            "",
            f"Open the crag: {settings.SITE_URL}{notice.url}",
            "",
            "You can choose which emails you get in your notification settings:",
            settings.SITE_URL + reverse("notification_settings"),
            "",
            "gr8base community",
        ])
        send_mail(subject, body, None, [user.email])
        logger.info("owner mail sent crag=%s user=%s kind=%s", crag.pk, user.pk, kind)
    except Exception:
        logger.exception("owner mail failed crag=%s kind=%s", crag.pk, kind)


def notify_owner(user, kind, crag, actor=None, count=1, email=True):
    """In the app and, if the user wants it, by email. Never raises."""
    notify_in_app(user, kind, crag, actor, count)
    if email:
        email_owner(user, kind, crag, actor, count)
