import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail, send_mass_mail
from django.db.models import Q
from django.urls import reverse

logger = logging.getLogger(__name__)


def notify_submitter(crag):
    """Mail the submitter about a publish or return. Never raises."""
    from .models import Crag

    try:
        user = crag.created_by
        if user is None or not user.email:
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
        emails = list(recipients.values_list("email", flat=True))
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
