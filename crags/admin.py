from django import forms
from django.contrib import admin, messages
from django.contrib.admin import helpers
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import UploadedFile

from .forms import process_image
from django.template.response import TemplateResponse

from .models import Area, Crag, InvalidTransition, CragComment, CragRating, Feature, Guidebook, Photo


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


class ReturnToSubmitterForm(forms.Form):
    reason = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 4}),
        min_length=Crag.MIN_REASON_LENGTH,
        help_text="Shown to the submitter.",
    )


@admin.register(Crag)
class CragAdmin(admin.ModelAdmin):
    filter_horizontal = ("guidebooks",)
    list_display = ("name", "area", "status", "created_by", "submitted_at", "updated_at")
    list_filter = ("status", "area")
    search_fields = ("name",)
    actions = ["publish", "return_to_submitter", "reject"]
    # Status changes go through the actions (Crag.transition) only.
    readonly_fields = ("status", "submitted_at", "reviewed_by", "reviewed_at", "review_reason")

    def get_actions(self, request):
        actions = super().get_actions(request)
        if not request.user.has_perm("crags.can_publish_crag"):
            return {}
        return actions

    def save_model(self, request, obj, form, change):
        if not change and obj.created_by is None:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

    def _transition_each(self, request, queryset, to, reason=""):
        done = 0
        for crag in queryset:
            try:
                crag.transition(to, request.user, reason)
            except (InvalidTransition, ValidationError) as exc:
                msg = exc.messages[0] if hasattr(exc, "messages") else str(exc)
                self.message_user(request, f"{crag}: {msg}", messages.ERROR)
            else:
                done += 1
        return done

    @admin.action(description="Publish selected crags")
    def publish(self, request, queryset):
        done = self._transition_each(request, queryset, Crag.Status.PUBLISHED)
        self.message_user(request, f"Published {done} crag(s).")

    @admin.action(description="Return selected crags to submitter")
    def return_to_submitter(self, request, queryset):
        if "apply" in request.POST:
            form = ReturnToSubmitterForm(request.POST)
            if form.is_valid():
                done = self._transition_each(
                    request, queryset, Crag.Status.NEEDS_CHANGES,
                    form.cleaned_data["reason"],
                )
                self.message_user(request, f"Returned {done} crag(s) to the submitter.")
                return None
        else:
            form = ReturnToSubmitterForm()
        return TemplateResponse(
            request,
            "admin/crags/return_to_submitter.html",
            {
                **self.admin_site.each_context(request),
                "title": "Return to submitter",
                "opts": self.model._meta,
                "crags": queryset,
                "form": form,
                "action_checkbox_name": helpers.ACTION_CHECKBOX_NAME,
            },
        )

    @admin.action(description="Reject selected crags")
    def reject(self, request, queryset):
        done = self._transition_each(request, queryset, Crag.Status.REJECTED)
        self.message_user(request, f"Rejected {done} crag(s).")


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


@admin.register(CragComment)
class CragCommentAdmin(admin.ModelAdmin):
    list_display = ("crag", "user", "created_at")
    search_fields = ("crag__name", "user__username", "text")
