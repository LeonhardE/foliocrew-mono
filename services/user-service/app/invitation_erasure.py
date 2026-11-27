"""Resolve current and former invitation addresses against a verified account."""

from folioview_shared.identity import owner_key

from .workspace_invitations import INVITATION_ID, invitation_id


class ErasureIncomplete(Exception):
    """The scope or readback changed. Keep the case open."""


class InvitationReviewRequired(ErasureIncomplete):
    """Legacy or inconsistent invitation ownership cannot be established."""


def joined_binding(row):
    owner = row.get("joinedOwner")
    google = row.get("joinedGoogleSubject")
    if (
        not isinstance(owner, str)
        or not INVITATION_ID.fullmatch(owner)
        or not isinstance(google, str)
        or not google
    ):
        # A legacy joined row can be orphaned after a partial old cleanup.
        raise InvitationReviewRequired
    return owner, google


def invitation_matches(key, row, subject):
    email = row.get("email")
    if not isinstance(email, str) or not email.isascii() or key != invitation_id(email):
        raise InvitationReviewRequired
    if row.get("status") == "joined":
        owner, google = joined_binding(row)
        if owner != owner_key(subject.uid):
            return False
        if google != subject.google_subject:
            raise InvitationReviewRequired
        return True
    if "joinedOwner" in row or "joinedGoogleSubject" in row:
        raise InvitationReviewRequired
    return email == subject.email
