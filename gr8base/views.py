import re
from pathlib import Path

import markdown
from django.conf import settings
from django.db import connection
from django.http import Http404, HttpResponse, JsonResponse
from django.templatetags.static import static
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST


CONTENT_DIR = Path(settings.BASE_DIR) / "content"
SLUG_PATTERN = re.compile(r"[-a-zA-Z0-9_]+")
INDEX_SLUG = "index"
FRONTMATTER_DELIMITER = "---"
LISTED_TAG = "faq"
UNORDERED = 10**6


def split_frontmatter(text):
    lines = text.splitlines()
    if not lines or lines[0].strip() != FRONTMATTER_DELIMITER:
        return {}, text
    try:
        end = next(
            i for i, line in enumerate(lines[1:], start=1)
            if line.strip() == FRONTMATTER_DELIMITER
        )
    except StopIteration:
        return {}, text

    meta = {}
    for line in lines[1:end]:
        key, sep, value = line.partition(":")
        if sep:
            meta[key.strip().lower()] = value.strip()
    return meta, "\n".join(lines[end + 1:])


def page_tags(meta):
    raw = meta.get("tags", "").strip("[]")
    return {tag.strip().strip("'\"").lower() for tag in raw.split(",") if tag.strip()}


def page_order(meta):
    try:
        return int(meta.get("order", ""))
    except ValueError:
        return UNORDERED


def read_page(path):
    return split_frontmatter(path.read_text(encoding="utf-8"))


def page_title(path, body):
    for line in body.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return path.stem.replace("-", " ").capitalize()


def render_markdown(text):
    md = markdown.Markdown(
        extensions=["toc", "tables", "fenced_code"],
        extension_configs={"toc": {"toc_depth": "2-3"}},
    )
    return md.convert(text), md.toc


def doc_index(request):
    intro = None
    index_path = CONTENT_DIR / f"{INDEX_SLUG}.md"
    if index_path.is_file():
        _, index_body = read_page(index_path)
        intro, _ = render_markdown(index_body)

    pages = []
    for path in sorted(CONTENT_DIR.glob("*.md")):
        if path.stem == INDEX_SLUG or not SLUG_PATTERN.fullmatch(path.stem):
            continue
        meta, body = read_page(path)
        if LISTED_TAG in page_tags(meta):
            pages.append({
                "slug": path.stem,
                "title": page_title(path, body),
                "order": page_order(meta),
            })

    pages.sort(key=lambda page: (page["order"], page["title"].lower()))
    return render(request, "docs.html", {"intro": intro, "pages": pages})


def doc_page(request, slug):
    path = CONTENT_DIR / f"{slug}.md"
    if not path.is_file():
        raise Http404("Page not found")

    _, body = read_page(path)
    html, toc = render_markdown(body)
    return render(
        request,
        "docs_page.html",
        {"title": page_title(path, body), "content": html, "toc": toc},
    )


def web_manifest(request):
    """Makes the site installable as an app (home screen icon, no browser bar).

    A view rather than a static file, so the icon URLs carry the hashed names.
    """
    response = JsonResponse(
        {
            "name": "gr8base community",
            "short_name": "gr8base",
            "description": "Find and share family-friendly climbing crags.",
            "start_url": "/",
            "scope": "/",
            "display": "standalone",
            "background_color": "#ffffff",
            "theme_color": "#0172ad",
            "icons": [
                {"src": static("icons/icon-192.png"), "sizes": "192x192", "type": "image/png"},
                {"src": static("icons/icon-512.png"), "sizes": "512x512", "type": "image/png"},
                {
                    "src": static("icons/icon-maskable-512.png"), "sizes": "512x512",
                    "type": "image/png", "purpose": "maskable",
                },
            ],
        },
        content_type="application/manifest+json",
    )
    response["Cache-Control"] = "public, max-age=86400"
    return response


def healthz(request):
    """Plain "ok" for the container check and uptime monitors."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:
        return HttpResponse("db unavailable", status=503, content_type="text/plain")
    # HEAD gets no body: gunicorn logs a warning for every HEAD response with one.
    body = "" if request.method == "HEAD" else "ok"
    return HttpResponse(body, content_type="text/plain")


def robots_txt(request):
    """Lets crawlers in, keeps them out of account/admin pages, points to the sitemap."""
    lines = [
        "User-agent: *",
        "Disallow: /admin/",
        "Disallow: /accounts/",
        "Disallow: /moderation/",
        "Disallow: /notifications/",
        "Disallow: /healthz/",
        "",
        f"Sitemap: {settings.SITE_URL}/sitemap.xml",
    ]
    return HttpResponse("\n".join(lines) + "\n", content_type="text/plain")


def site_icon(request):
    """Browsers and crawlers ask for /favicon.ico and /apple-touch-icon*.png at the root."""
    name = "favicon-32.png" if "favicon" in request.path else "apple-touch-icon.png"
    return redirect(static(f"icons/{name}"))


CONSENT_COOKIE = "cookie_consent"
CONSENT_MAX_AGE = 180 * 24 * 3600
VISITOR_COOKIE = "seen_today"


@require_POST
def cookie_consent(request):
    """Store the visitor-counter choice: accept, decline or reset (ask again)."""
    choice = request.POST.get("choice")
    target = request.POST.get("next", "")
    if not url_has_allowed_host_and_scheme(
        target, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        target = "/"
    response = redirect(target)
    if choice == "accept":
        response.set_cookie(
            CONSENT_COOKIE, "yes", max_age=CONSENT_MAX_AGE,
            secure=request.is_secure(), httponly=True, samesite="Lax",
        )
    else:
        response.delete_cookie(VISITOR_COOKIE)
        if choice == "decline":
            response.set_cookie(
                CONSENT_COOKIE, "no", max_age=CONSENT_MAX_AGE,
                secure=request.is_secure(), httponly=True, samesite="Lax",
            )
        else:
            response.delete_cookie(CONSENT_COOKIE)
    return response
