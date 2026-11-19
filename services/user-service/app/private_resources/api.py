"""Opt-in Owner recovery evidence from the User private resource module."""

import os
import re
import time
from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from pydantic import RootModel
from starlette.concurrency import run_in_threadpool

from folioview_shared.auth import CurrentUser, require_google_user
from folioview_shared.delegation import DelegationError, DelegationVerifier
from folioview_shared.encrypted.constants import CONTRACT_VERSION
from folioview_shared.encrypted.errors import ContractError
from folioview_shared.encrypted.jsonutil import strict_json_loads
from folioview_shared.service_identity import (
    GoogleCallerVerifier,
    IdentityVerificationUnavailable,
    InvalidIdentityToken,
    UntrustedServiceCaller,
)

from ..resource_api import ResourceRoute, body, configured_verifier, require_v2
from ..resources import FirestoreUserResourceStore, get_resource_store
from .recovery import RecoveryHeads, RecoveryRequest, current_recovery_evidence
from .registry_pages import RegistryHistory, RegistryPageRequest
from .report_sources import ReportSourceAuthority

router = APIRouter(
    prefix="/api/v3/private-resources/vaults", tags=["private-resources"], route_class=ResourceRoute
)
internal = APIRouter(tags=["private-resources"], route_class=ResourceRoute)
REPORT_DECISION_PATH = "/internal/v2/private-resources/report-source-decisions"
OWNER_PROXY_HEADER = "x-folioview-proxy-authorization"
_USER_ORIGIN = re.compile(r"https://user-api-[0-9]{1,20}\.[a-z]+(?:-[a-z0-9]+)+[0-9]\.run\.app\Z")


@lru_cache(maxsize=4)
def configured_owner_proxy(audience, encoded_callers):
    try:
        if _USER_ORIGIN.fullmatch(audience) is None:
            raise ValueError
        callers = strict_json_loads(encoded_callers, max_bytes=2048)
        if type(callers) is not dict or len(callers) != 1:
            raise ValueError
        return GoogleCallerVerifier(audience, callers)
    except (ContractError, ValueError, TypeError):
        raise ContractError("authorization_unavailable") from None


def require_owner_proxy(request: Request) -> None:
    if request.url.query:
        raise ContractError("unsupported_query")
    require_v2(request)
    credentials = request.headers.getlist(OWNER_PROXY_HEADER)
    if len(credentials) != 1:
        raise ContractError("invalid_token")
    scheme, _, token = credentials[0].partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise ContractError("invalid_token")
    verifier = configured_owner_proxy(
        os.getenv("USER_PRIVATE_OWNER_AUDIENCE", ""),
        os.getenv("USER_PRIVATE_OWNER_WEB_CALLER", ""),
    )
    try:
        verifier.verify(token)
    except InvalidIdentityToken:
        raise ContractError("invalid_token") from None
    except UntrustedServiceCaller:
        raise ContractError("insufficient_scope") from None
    except IdentityVerificationUnavailable:
        raise ContractError("authorization_unavailable") from None


def report_authority() -> ReportSourceAuthority:
    if os.getenv("USER_REPORT_SOURCE_DECISIONS") != "true":
        raise ContractError("not_found")
    store = get_resource_store()
    if "K_SERVICE" in os.environ and (
        not isinstance(store, FirestoreUserResourceStore) or store.client._database != "user-data"
    ):
        raise ContractError("authorization_unavailable")
    return ReportSourceAuthority(store)


def report_verifier():
    return configured_verifier(
        tuple(
            os.getenv(key, "")
            for key in (
                "USER_SERVICE_AUDIENCE",
                "USER_REPORT_DELEGATION_AUDIENCE",
                "USER_DELEGATION_ISSUER",
                "USER_TRUSTED_HUB_CALLERS",
            )
        ),
        REPORT_DECISION_PATH,
    )


@internal.post(REPORT_DECISION_PATH)
async def report_source_decision(
    request: Request,
    response: Response,
    authority: Annotated[ReportSourceAuthority, Depends(report_authority)],
    verifier: Annotated[DelegationVerifier, Depends(report_verifier)],
):
    require_v2(request)
    authorization = request.headers.getlist("authorization")
    delegation = request.headers.getlist("x-folioview-delegation")
    if len(authorization) != 1 or len(delegation) != 1:
        raise ContractError("invalid_token")
    scheme, _, workload = authorization[0].partition(" ")
    if scheme.lower() != "bearer" or not workload or not delegation[0]:
        raise ContractError("invalid_token")
    value = (await body(request, RootModel[dict[str, object]])).root
    try:
        uid = await run_in_threadpool(
            verifier.verify_report_attempt, workload, delegation[0], request=value
        )
    except DelegationError as error:
        code = {
            "invalid_credentials": "invalid_token",
            "permission_denied": "insufficient_scope",
            "verification_unavailable": "authorization_unavailable",
        }[error.code]
        raise ContractError(code) from None
    result = await run_in_threadpool(authority.decide, uid, value)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-FolioView-Contract"] = CONTRACT_VERSION
    return result


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
    response: Response,
    user: Annotated[CurrentUser, Depends(require_google_user)],
    store: Annotated[RecoveryHeads, Depends(owner_recovery_store)],
    _: Annotated[None, Depends(require_owner_proxy)],
):
    value = await body(request, RecoveryRequest)
    result = await run_in_threadpool(
        current_recovery_evidence, store, user.uid, vault_id, value.model_dump(), int(time.time())
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-FolioView-Contract"] = CONTRACT_VERSION
    return result


@router.post("/{vault_id}/registry-pages/read")
async def registry_page(
    vault_id: str,
    request: Request,
    response: Response,
    user: Annotated[CurrentUser, Depends(require_google_user)],
    store: Annotated[RecoveryHeads, Depends(owner_recovery_store)],
    _: Annotated[None, Depends(require_owner_proxy)],
):
    value = await body(request, RegistryPageRequest)
    result = await run_in_threadpool(RegistryHistory(store).page, user.uid, vault_id, value)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-FolioView-Contract"] = CONTRACT_VERSION
    return result
