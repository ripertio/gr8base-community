from .models import Crag, Notification


def nav_counts(request):
    """Counters in the navigation (templates/base.html).

    unread_notification_count: next to the user's name, links to /notifications/.
    open_moderation_count: crags waiting for review, next to "Moderation" (only
    for those who see that link: staff and publishers).
    nav_total_count: both together, on the burger icon of the collapsed menu.
    """
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {}
    counts = {"unread_notification_count": Notification.unread_for(user).count()}
    if user.is_staff or user.has_perm("crags.can_publish_crag"):
        counts["open_moderation_count"] = Crag.objects.filter(
            status=Crag.Status.PENDING
        ).count()
    counts["nav_total_count"] = sum(counts.values())
    return counts
