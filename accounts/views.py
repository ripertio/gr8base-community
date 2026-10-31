from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render

from crags.models import Crag

from .forms import ProfileForm


def profile_detail(request, username):
    profile_user = get_object_or_404(get_user_model(), username=username)
    is_owner = request.user == profile_user
    if not (profile_user.profile_public or is_owner or request.user.is_staff):
        raise Http404
    crags = (
        Crag.objects.filter(created_by=profile_user)
        .public()
        .select_related("area")
        .order_by("name")
    )
    return render(
        request,
        "accounts/profile_detail.html",
        {"profile_user": profile_user, "crags": crags, "is_owner": is_owner},
    )


@login_required
def profile_edit(request):
    form = ProfileForm(
        request.POST or None, request.FILES or None, instance=request.user
    )
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Profile saved.")
        return redirect("profiles:detail", username=request.user.username)
    return render(request, "accounts/profile_form.html", {"form": form})
