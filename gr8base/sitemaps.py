from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from crags.models import Crag


class StaticPages(Sitemap):
    protocol = "https"
    changefreq = "weekly"

    def items(self):
        return ["crags:list", "docs"]

    def location(self, name):
        return reverse(name)


class PublicCrags(Sitemap):
    """Crags anonymous visitors may see (same rule as the crag pages)."""

    protocol = "https"
    changefreq = "weekly"

    def items(self):
        return Crag.objects.public().order_by("pk")

    def location(self, crag):
        return reverse("crags:detail", args=[crag.pk])

    def lastmod(self, crag):
        return crag.updated_at


SITEMAPS = {"pages": StaticPages, "crags": PublicCrags}
