import re
from pathlib import Path

import markdown
from django.conf import settings
from django.http import Http404
from django.shortcuts import render

CONTENT_DIR = Path(settings.BASE_DIR) / "content"
SLUG_PATTERN = re.compile(r"[-a-zA-Z0-9_]+")
INDEX_SLUG = "index"


def page_title(path):
    for line in path.read_text(encoding="utf-8").splitlines():
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
        intro, _ = render_markdown(index_path.read_text(encoding="utf-8"))

    pages = [
        {"slug": path.stem, "title": page_title(path)}
        for path in sorted(CONTENT_DIR.glob("*.md"))
        if path.stem != INDEX_SLUG and SLUG_PATTERN.fullmatch(path.stem)
    ]
    return render(request, "docs.html", {"intro": intro, "pages": pages})


def doc_page(request, slug):
    path = CONTENT_DIR / f"{slug}.md"
    if not path.is_file():
        raise Http404("Page not found")

    html, toc = render_markdown(path.read_text(encoding="utf-8"))
    return render(
        request,
        "docs_page.html",
        {"title": page_title(path), "content": html, "toc": toc},
    )
