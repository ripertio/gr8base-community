from .moderation import open_task_count
from .models import Notification
from .notifications import can_moderate, wants


def nav_counts(request):
    """Counters in the navigation (templates/base.html).

    unread_notification_count: next to the user's name, links to /notifications/.
    open_moderation_count: crags waiting for review, next to "Moderation" (only
    for those who see that link: staff and publishers, and only if they did not
    switch it off in their notification settings).
    nav_total_count: both together, on the burger icon of the collapsed menu.
    """
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {}
    counts = {"unread_notification_count": Notification.unread_for(user).count()}
    if can_moderate(user) and wants(user, "REVIEW_WAITING", "in_app"):
        counts["open_moderation_count"] = open_task_count()
    counts["nav_total_count"] = sum(counts.values())
    return counts
