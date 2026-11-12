# Roles and Permissions

There are three kinds of privileged users. They build on each other:

- **Staff**: a user with `is_staff` and nothing else. Can log in to the Django admin, but sees nothing there without permissions.
- **Crag Manager**: a staff user who is also in the **Crag Managers** group. The group carries the admin permissions below.
- **Superuser**: `is_superuser` (always also staff). Has every permission without needing a group.

A Crag Manager is therefore not a separate account type, but staff plus a group. Each column includes everything from the column to its left, with one exception: superusers are not counted in the visitor stats.

| | Staff | Crag Manager | Superuser |
|---|---|---|---|
| **Public site** | | | |
| See every crag, including others' drafts | yes | yes | yes |
| Edit any crag, add or delete photos on any crag | yes | yes | yes |
| Edit a published crag without sending it back to review | no | yes | yes |
| Delete any comment | yes | yes | yes |
| No photo limit (otherwise 8 per crag) | yes | yes | yes |
| See visitor charts on the stats page | yes | yes | yes |
| Open the moderation page (`/moderation/`) | yes | yes | yes |
| Remove (soft delete) any crag | own crags only | yes | yes |
| View private profiles | no | no | yes |
| **Django admin** | | | |
| Log in to the admin | yes (sees nothing) | yes | yes |
| Add and edit crags, areas, guidebooks | no | yes | yes |
| Delete areas and guidebooks | no | yes | yes |
| Publish, return or reject crags | no | yes | yes |
| "Publish" button on the crag page and "Save and publish" on the edit page (pending crags only) | no | yes | yes |
| Hard delete crags | no | no | yes |
| Restore removed crags | no | no | yes |
| Change a crag to any status (see below) | no | no | yes |
| Manage users and groups | no | no | yes |
| **Other** | | | |
| Counted in visitor stats | yes | yes | no |

Regular users can see all published and pending crags and their own crags in any status. They can edit and remove their own crags.

## Removing crags

"Remove" is a soft delete: the crag gets the status **Removed**. It stays in the database with its photos, comments and ratings, but it is hidden everywhere on the public site, for everyone, the owner and staff included (404). Removed crags show up only in the Django admin, in the crag list (filter "By status" → "Removed"), where Crag Managers and superusers can see them.

- **Who can remove:** the owner of the crag, or anyone with the `crags.can_remove_crag` permission (Crag Managers have it). Plain staff cannot remove other people's crags. A crag can be removed from any status.
- **Restore:** only users with `crags.delete_crag` (superusers) can restore, with the admin action "Restore removed crags". A restored crag becomes a **draft** again (private), so it has to be submitted and reviewed again.
- **Hard delete:** also only for `crags.delete_crag`, in the admin. It removes the photos too.
- Deleting an area is refused while it still has crags, removed ones included.
- Technically, `Crag.objects` excludes removed crags and `Crag.all_objects` includes them (used by the admin only).

## Changing status as superuser

Normally a crag follows the review flow (`Crag.ALLOWED_TRANSITIONS`): for example, a draft can only be submitted, and a rejected crag has no way forward. Superusers can override this in the admin: select crags in the list, run **"Change status (superuser: any status to any status)"**, pick the target status (and a reason, which is required for "Needs changes"). Examples: Removed → Published, Needs changes → Published, Rejected → Pending review.

The override still goes through `Crag.transition(..., force=True)`, so the audit fields (`reviewed_by`, `reviewed_at`, `submitted_at`) are set as for a normal change and the submitter gets the usual email when a crag is published or returned. It only skips the table of allowed moves. Choosing the status a crag already has is refused. Crag Managers do not get this action.

## Where it is implemented

| Rule | Code |
|---|---|
| Group and its permissions | migrations `crags/migrations/0010`, `0014`, `0017`, `0018`, `0019` |
| Custom permissions `can_publish_crag`, `can_remove_crag` | `Crag.Meta.permissions` in `crags/models.py` |
| Hiding removed crags | default manager `Crag.objects` in `crags/models.py` |
| Edit and remove rules on the public site | `editable_crags`, `removable_crags` in `crags/views.py` |
| Admin actions (publish, return, reject, restore, change status) | `CragAdmin` in `crags/admin.py` |
| Private profiles | `profile_detail` in `accounts/views.py` |
