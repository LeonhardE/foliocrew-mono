"""Gate Agent enrollment and runtime access independently of resource consent."""

import os
import re

from folioview_shared.encrypted.errors import ContractError
from folioview_shared.encrypted.jsonutil import strict_json_loads
from folioview_shared.identity import owner_key

ENVIRONMENT = "HUB_AGENT_OWNED_ALLOWED_OWNER_SUBJECTS_JSON"
ADMITTED_USERS_ENVIRONMENT = "HUB_AGENT_OWNED_ADMITTED_USERS_ENABLED"
WORKSPACE_ADMISSION = "workspaceAdmission"


def admitted_users_enabled():
    return (
        os.getenv(ADMITTED_USERS_ENVIRONMENT) == "1"
        and os.getenv("FOLIOCREW_REQUIRE_ADMISSION_CLAIM") == "1"
    )


def _pilot_owner_allowed(subject):
    raw = os.getenv(ENVIRONMENT)
    if raw is None:
        return os.getenv(ADMITTED_USERS_ENVIRONMENT) != "1"
    try:
        owners = strict_json_loads(raw, max_bytes=4096)
        if (
            type(owners) is not list
            or len(owners) > 32
            or any(type(o) is not str or re.fullmatch(r"[a-f0-9]{64}", o) is None for o in owners)
            or len(set(owners)) != len(owners)
        ):
            return False
        return subject in owners
    except ContractError:
        return False


def owner_allowed(subject, *, connection=None):
    return _pilot_owner_allowed(subject) or (
        admitted_users_enabled()
        and connection is not None
        and connection.get("ownerSubject") == subject
        and connection.get("transportKind") == "persistent_runtime"
        and connection.get(WORKSPACE_ADMISSION) is True
    )


def require_owner_allowed(subject, *, connection=None):
    if not owner_allowed(subject, connection=connection):
        raise ContractError("authorization_unavailable")


def require_owner_enrollment(subject):
    # Owner routes have already verified the configured Firebase admission claim.
    if not admitted_users_enabled() and not _pilot_owner_allowed(subject):
        raise ContractError("authorization_unavailable")


def uid_allowed(uid):
    return admitted_users_enabled() or _pilot_owner_allowed(owner_key(uid))
