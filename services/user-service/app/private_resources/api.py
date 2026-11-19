"""Opt-in Owner recovery evidence from the User private resource module."""

import os
import time
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from starlette.concurrency import run_in_threadpool

from folioview_shared.auth import CurrentUser, require_google_user
from folioview_shared.encrypted.errors import ContractError

from ..resource_api import ResourceRoute, body
from ..resources import FirestoreUserResourceStore, get_resource_store
from .recovery import RecoveryHeads, RecoveryRequest, current_recovery_evidence
from .registry_pages import RegistryHistory, RegistryPageRequest

router = APIRouter(
    prefix="/api/v3/private-resources/vaults", tags=["private-resources"], route_class=ResourceRoute
)


def owner_recovery_store() -> RecoveryHeads:
    if os.getenv("USER_PRIVATE_RECOVERY_READ") != "true":
        raise ContractError("not_found")
    store = get_resource_store()
    if "K_SERVICE" in os.environ and (
        not isinstance(store, FirestoreUserResourceStore) or store.client._database != "user-data"
    ):
        raise ContractError("authorization_unavailable")
    return RecoveryHeads(store)


@router.post("/{vault_id}/recovery-evidence")
async def recovery_evidence(
    vault_id: str,
    request: Request,
    user: Annotated[CurrentUser, Depends(require_google_user)],
    store: Annotated[RecoveryHeads, Depends(owner_recovery_store)],
):
    value = await body(request, RecoveryRequest)
    return await run_in_threadpool(
        current_recovery_evidence, store, user.uid, vault_id, value.model_dump(), int(time.time())
    )


@router.post("/{vault_id}/registry-pages/read")
async def registry_page(
    vault_id: str,
    request: Request,
    user: Annotated[CurrentUser, Depends(require_google_user)],
    store: Annotated[RecoveryHeads, Depends(owner_recovery_store)],
):
    value = await body(request, RegistryPageRequest)
    return await run_in_threadpool(RegistryHistory(store).page, user.uid, vault_id, value)
