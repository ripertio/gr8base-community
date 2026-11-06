from django import forms
from django.contrib import admin
from django.core.files.uploadedfile import UploadedFile

from .forms import process_image
from .models import Area, Crag, CragRating, Feature, Guidebook, Photo


@admin.register(Area)
class AreaAdmin(admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)


@admin.register(Feature)
class FeatureAdmin(admin.ModelAdmin):
    list_display = ("label", "slug")
    search_fields = ("label", "slug")



class GuidebookAdminForm(forms.ModelForm):
    class Meta:
        model = Guidebook
        fields = "__all__"

    def clean_picture(self):
        picture = self.cleaned_data.get("picture")
        # Only new uploads are processed; an unchanged or cleared value passes through.
        if isinstance(picture, UploadedFile):
            return process_image(picture, max_edge=800)
        return picture


@admin.register(Guidebook)
class GuidebookAdmin(admin.ModelAdmin):
    form = GuidebookAdminForm
    list_display = ("name", "publisher", "publish_year")
    list_filter = ("publish_year",)
    search_fields = ("name", "publisher")


@admin.register(Crag)
class CragAdmin(admin.ModelAdmin):
    filter_horizontal = ("guidebooks",)
    list_display = ("name", "area", "status", "created_by", "updated_at")
    list_filter = ("status", "area")
    search_fields = ("name",)
    actions = ["publish", "reject"]

    def save_model(self, request, obj, form, change):
        if not change and obj.created_by is None:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

    @admin.action(description="Publish selected crags")
    def publish(self, request, queryset):
        queryset.update(status=Crag.Status.PUBLISHED)

    @admin.action(description="Reject selected crags")
    def reject(self, request, queryset):
        queryset.update(status=Crag.Status.REJECTED)


@admin.register(Photo)
class PhotoAdmin(admin.ModelAdmin):
    list_display = (
        "crag",
        "caption",
        "created_at",
    )


@admin.register(CragRating)
class CragRatingAdmin(admin.ModelAdmin):
    list_display = ("crag", "user", "rating_babies", "rating_ages_2_4", "rating_ages_5_plus", "updated_at")
    search_fields = ("crag__name", "user__username")
