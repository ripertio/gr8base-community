import logging

from django.conf import settings
from django.core.mail import send_mail
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
