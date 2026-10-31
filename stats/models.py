from django.db import models


class DailyHits(models.Model):
    """Page views per day. No visitor data is stored, only a counter."""

    date = models.DateField(unique=True)
    count = models.PositiveIntegerField(default=0)
    logged_in_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["date"]
        verbose_name_plural = "daily hits"

    def __str__(self):
        return f"{self.date}: {self.count}"
