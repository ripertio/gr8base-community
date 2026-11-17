from django import forms
from django.contrib import admin, messages
from django.contrib.admin import helpers
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import UploadedFile

from django.db.models import Count

from .forms import process_image
from django.template.response import TemplateResponse

from django.utils.html import format_html

from .models import (
    Area, ChangeRequest, ChangeRequestMessage, ChangeRequestPhoto, Crag, InvalidTransition,
    CragComment, CragRating, Feature, Guidebook, Notification, Photo, ReviewMessage,
)


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


class ChangeStatusForm(forms.Form):
    status = forms.ChoiceField(choices=Crag.Status.choices)
    reason = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text=(
            f"Required (at least {Crag.MIN_REASON_LENGTH} characters) for "
            "\u201cNeeds changes\u201d; shown to the submitter."
        ),
    )

    def clean(self):
        data = super().clean()
        reason = (data.get("reason") or "").strip()
        if (
            data.get("status") == Crag.Status.NEEDS_CHANGES
            and len(reason) < Crag.MIN_REASON_LENGTH
        ):
            self.add_error(
                "reason",
                f"A reason of at least {Crag.MIN_REASON_LENGTH} characters is required.",
            )
        return data


class ReviewQueueFilter(admin.SimpleListFilter):
    title = "review queue"
    parameter_name = "queue"

    def lookups(self, request, model_admin):
        return [("pending", "Pending review (oldest first)")]

    def queryset(self, request, queryset):
        if self.value() == "pending":
            return queryset.filter(status=Crag.Status.PENDING)
        return queryset


@admin.register(Crag)
class CragAdmin(admin.ModelAdmin):
    filter_horizontal = ("guidebooks",)
    list_display = (
        "name", "area", "status", "created_by", "submitted_at", "photo_count", "updated_at",
    )
    list_filter = (ReviewQueueFilter, "status", "area")
    search_fields = ("name",)
    actions = ["publish", "return_to_submitter", "reject", "restore", "change_status"]
    # Status changes go through the actions (Crag.transition) only.
    readonly_fields = ("status", "submitted_at", "reviewed_by", "reviewed_at", "review_reason")

    def get_queryset(self, request):
        # all_objects: the default manager hides removed crags.
        qs = Crag.all_objects.all()
        ordering = self.get_ordering(request)
        if ordering:
            qs = qs.order_by(*ordering)
        return qs.annotate(_photo_count=Count("photos"))

    def get_ordering(self, request):
        if request.GET.get("queue") == "pending":
            return ["submitted_at", "pk"]
        return super().get_ordering(request)

    @admin.display(description="Photos", ordering="_photo_count")
    def photo_count(self, obj):
        return obj._photo_count

    def get_actions(self, request):
        actions = super().get_actions(request)
        if not request.user.has_perm("crags.can_publish_crag"):
            for name in ("publish", "return_to_submitter", "reject"):
                actions.pop(name, None)
        # Restoring removed crags goes with hard delete: superusers only.
        if not request.user.has_perm("crags.delete_crag"):
            actions.pop("restore", None)
        if not request.user.is_superuser:
            actions.pop("change_status", None)
        return actions

    def save_model(self, request, obj, form, change):
        if not change and obj.created_by is None:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

    def _transition_each(self, request, queryset, to, reason="", force=False):
        done = 0
        for crag in queryset:
            try:
                crag.transition(to, request.user, reason, force=force)
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

    @admin.action(description="Restore removed crags")
    def restore(self, request, queryset):
        done = self._transition_each(
            request, queryset.filter(status=Crag.Status.REMOVED), Crag.Status.DRAFT
        )
        self.message_user(request, f"Restored {done} crag(s) as drafts.")

    @admin.action(description="Change status (superuser: any status to any status)")
    def change_status(self, request, queryset):
        if not request.user.is_superuser:
            raise PermissionDenied
        if "apply" in request.POST:
            form = ChangeStatusForm(request.POST)
            if form.is_valid():
                done = self._transition_each(
                    request, queryset, form.cleaned_data["status"],
                    form.cleaned_data["reason"], force=True,
                )
                self.message_user(request, f"Changed the status of {done} crag(s).")
                return None
        else:
            form = ChangeStatusForm()
        return TemplateResponse(
            request,
            "admin/crags/change_status.html",
            {
                **self.admin_site.each_context(request),
                "title": "Change status",
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


class SuperuserCleanupMixin:
    """Read-only in the admin; only superusers see it and may delete (clean up).

    Change requests are created and handled on the site; the admin is for looking
    and cleaning up, so nothing is added or edited here.
    """

    def has_module_permission(self, request):
        return request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


class ChangeRequestMessageInline(SuperuserCleanupMixin, admin.TabularInline):
    model = ChangeRequestMessage
    fields = ("created_at", "author", "kind", "text")
    readonly_fields = fields
    extra = 0


class ChangeRequestPhotoInline(SuperuserCleanupMixin, admin.TabularInline):
    model = ChangeRequestPhoto
    fields = ("preview", "category", "uploaded_by", "created_at")
    readonly_fields = fields
    extra = 0

    @admin.display(description="Photo")
    def preview(self, obj):
        return format_html('<img src="{}" alt="" style="max-height:6rem">', obj.image.url)


@admin.register(ChangeRequest)
class ChangeRequestAdmin(SuperuserCleanupMixin, admin.ModelAdmin):
    """Suggested changes ("Suggest a change"). Superusers clean up here:
    "Delete selected" removes requests with their messages, photo files and
    notifications; "Delete suggested photos" keeps the text history."""

    list_display = ("crag", "topic", "requester", "status", "photo_count", "created_at", "closed_at")
    list_filter = ("status", "topic")
    search_fields = ("crag__name", "requester__username", "text")
    date_hierarchy = "created_at"
    fields = ("crag", "requester", "topic", "text", "status", "created_at", "closed_by", "closed_at")
    readonly_fields = fields
    inlines = (ChangeRequestMessageInline, ChangeRequestPhotoInline)
    actions = ["delete_suggested_photos"]

    def get_queryset(self, request):
        return (
            super().get_queryset(request)
            .select_related("crag", "requester")
            .annotate(photo_total=Count("photos"))
        )

    @admin.display(description="Photos", ordering="photo_total")
    def photo_count(self, obj):
        return obj.photo_total

    @admin.action(description="Delete suggested photos (keep the requests)")
    def delete_suggested_photos(self, request, queryset):
        if not request.user.is_superuser:
            raise PermissionDenied
        # files go with the rows (post_delete signal)
        deleted, _ = ChangeRequestPhoto.objects.filter(change_request__in=queryset).delete()
        self.message_user(request, f"Deleted {deleted} suggested photo(s).", messages.SUCCESS)


@admin.register(ReviewMessage)
class ReviewMessageAdmin(SuperuserCleanupMixin, admin.ModelAdmin):
    """The private review conversations (moderators' "Needs changes" and the replies).

    Superusers clean up here: "Delete selected" removes single entries; "Delete
    the whole review" removes every entry of the selected crags' reviews and the
    notifications pointing to them.
    """

    list_display = ("crag", "kind", "author", "short_text", "created_at")
    list_filter = ("kind", "crag__status")
    search_fields = ("crag__name", "author__username", "text")
    date_hierarchy = "created_at"
    fields = ("crag", "kind", "author", "text", "created_at")
    readonly_fields = fields
    actions = ["delete_whole_reviews"]

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("crag", "author")

    @admin.display(description="Text")
    def short_text(self, obj):
        return obj.text[:80] + ("…" if len(obj.text) > 80 else "")

    @admin.action(description="Delete the whole review of the selected crags")
    def delete_whole_reviews(self, request, queryset):
        if not request.user.is_superuser:
            raise PermissionDenied
        crag_ids = list(queryset.values_list("crag_id", flat=True).distinct())
        deleted, _ = ReviewMessage.objects.filter(crag_id__in=crag_ids).delete()
        Notification.objects.filter(
            kind=Notification.Kind.REVIEW_MESSAGE, crag_id__in=crag_ids
        ).delete()
        self.message_user(
            request,
            f"Deleted {deleted} review entr{'y' if deleted == 1 else 'ies'} "
            f"of {len(crag_ids)} crag{'' if len(crag_ids) == 1 else 's'}.",
            messages.SUCCESS,
        )
