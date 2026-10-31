from django.contrib import admin

from .models import Area, Crag, Feature, Photo


@admin.register(Area)
class AreaAdmin(admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)


@admin.register(Feature)
class FeatureAdmin(admin.ModelAdmin):
    list_display = ("label", "slug")
    search_fields = ("label", "slug")



@admin.register(Crag)
class CragAdmin(admin.ModelAdmin):
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