"""Server side of the offline support (see templates/sw.js).

The service worker stores a page for offline use only when the response carries
OFFLINE_HEADER. Views opt in with @offline_cacheable, so every other page
(forms, accounts, admin, moderation, ...) is never stored on the device.
"""
from functools import wraps

OFFLINE_HEADER = "X-Offline-Cache"


def offline_cacheable(view):
    """Allow the service worker to keep this page for offline reading.

    Not for responses that show a one-time message ("Crag published."): a stored
    copy would show it again every time the page is opened offline.
    """

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        response = view(request, *args, **kwargs)
        messages = getattr(request, "_messages", None)
        if (
            request.method == "GET"
            and response.status_code == 200
            and not (messages is not None and len(messages))
        ):
            response[OFFLINE_HEADER] = "1"
        return response

    return wrapper
