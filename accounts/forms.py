from django import forms

from crags.forms import process_image

from .models import User

AVATAR_MAX_EDGE = 400


class ProfileForm(forms.ModelForm):
    remove_avatar = forms.BooleanField(required=False, label="Remove avatar")

    class Meta:
        model = User
        fields = ["bio", "avatar", "profile_public"]
        widgets = {"bio": forms.Textarea(attrs={"rows": 4})}
        labels = {"profile_public": "Make my profile public"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # _post_clean overwrites instance.avatar, so remember the stored file now.
        self.old_avatar_name = self.instance.avatar.name if self.instance.avatar else ""

    def clean_avatar(self):
        avatar = self.cleaned_data.get("avatar")
        # Only process a fresh upload, not the already stored file.
        if avatar and hasattr(avatar, "content_type"):
            return process_image(avatar, max_edge=AVATAR_MAX_EDGE)
        return avatar

    def save(self, commit=True):
        old_name = self.old_avatar_name
        user = super().save(commit=False)
        replaced = "avatar" in self.changed_data
        if self.cleaned_data.get("remove_avatar") and not replaced:
            user.avatar = ""
            replaced = True
        if commit:
            user.save()
            if replaced and old_name and old_name != user.avatar.name:
                user.avatar.storage.delete(old_name)
        return user
