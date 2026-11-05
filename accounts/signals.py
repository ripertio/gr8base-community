import logging

from allauth.account.signals import user_signed_up
from django.dispatch import receiver

logger = logging.getLogger(__name__)


@receiver(user_signed_up)
def log_signup(request, user, **kwargs):
    # ID only: no username or e-mail address in the logs.
    logger.info("user signed up id=%s", user.pk)
