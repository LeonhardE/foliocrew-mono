"""Opt-in Owner recovery evidence from the User private resource module."""

import os
import re
import time
from functools import lru_cache
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import RootModel
from starlette.concurrency import run_in_threadpool

from folioview_shared.auth import CurrentUser, require_google_user
from folioview_shared.delegation import DelegationError, DelegationVerifier
from folioview_shared.encrypted.constants import (
    CONTRACT_VERSION,
    MAX_CONTROL_BYTES,
    MAX_REGISTRY_BYTES,
)
from folioview_shared.encrypted.errors import ContractError
from folioview_shared.encrypted.jsonutil import strict_json_loads
from folioview_shared.encrypted.private_display_names import (
    DISPLAY_NAME_PROFILE,
    MAX_DISPLAY_COMMAND_BYTES,
)
from folioview_shared.identity import owner_key
from folioview_shared.service_identity import (
    GoogleCallerVerifier,
    IdentityVerificationUnavailable,
    InvalidIdentityToken,
    UntrustedServiceCaller,
)

from ..resource_api import ResourceRoute, body, configured_verifier, require_v2
from ..resources import FirestoreUserResourceStore, get_resource_store
from .archive_lifecycle import PROFILE as ARCHIVE_LIFECYCLE_PROFILE
from .archive_lifecycle import PrivateArchiveLifecycle
from .authority_cutover import UserAuthorityCutover
from .authority_views import OWNER_CURRENT_PROFILE, PrivateAuthorityViews
from .directory import DIRECTORY_PROFILE, PrivateResourceDirectory
from .display_names import PrivateDisplayNames
from .key_renewals import PrivateKeyRenewals
from .recovery import (
    ClosedModel,
    Digest,
    Identifier,
    OperationId,
    RecoveryHeads,
    RecoveryRequest,
    current_recovery_evidence,
)
from .registry_pages import RegistryHistory, RegistryPageRequest
from .registry_transition import MAX_TRANSITION_PACKET_BYTES
from .registry_updates import RegistryUpdate, RegistryUpdates
from .report_sources import ReportSourceAuthority
from .source_invalidations import PortfolioSourceRevision, SourceInvalidations
from .source_registrations import HoldingsRegistrations

router = APIRouter(
    prefix="/api/v3/private-resources/vaults", tags=["private-resources"], route_class=ResourceRoute
)
internal = APIRouter(tags=["private-resources"], route_class=ResourceRoute)
REPORT_DECISION_PATH = "/internal/v2/private-resources/report-source-decisions"
PORTFOLIO_FENCE_PATH = "/internal/v2/private-resources/source-fences"
PORTFOLIO_REVISION_PATH = "/internal/v2/private-resources/source-revisions"
OWNER_PROXY_HEADER = "x-folioview-proxy-authorization"
_USER_ORIGIN = re.compile(r"https://user-api-[0-9]{1,20}\.[a-z]+(?:-[a-z0-9]+)+[0-9]\.run\.app\Z")


def require_selected_private_owner(subject: str) -> None:
    selected = os.getenv("USER_PRIVATE_SELECTED_OWNER")
    if selected is None and "K_SERVICE" not in os.environ:
        return
    if selected is None or re.fullmatch(r"[a-f0-9]{64}", selected) is None:
        raise ContractError("authorization_unavailable")
    if subject != selected:
        raise ContractError("not_found")


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
    _require_private_workload(
        request,
        header=OWNER_PROXY_HEADER,
        audience_env="USER_PRIVATE_OWNER_AUDIENCE",
        caller_env="USER_PRIVATE_OWNER_WEB_CALLER",
    )


def _require_private_workload(request: Request, *, header, audience_env, caller_env) -> None:
    if request.url.query:
        raise ContractError("unsupported_query")
    require_v2(request)
    credentials = request.headers.getlist(header)
    if len(credentials) != 1:
        raise ContractError("invalid_token")
    scheme, _, token = credentials[0].partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise ContractError("invalid_token")
    verifier = configured_owner_proxy(os.getenv(audience_env, ""), os.getenv(caller_env, ""))
    try:
        verifier.verify(token)
    except InvalidIdentityToken:
        raise ContractError("invalid_token") from None
    except UntrustedServiceCaller:
        raise ContractError("insufficient_scope") from None
    except IdentityVerificationUnavailable:
        raise ContractError("authorization_unavailable") from None


def portfolio_invalidation() -> SourceInvalidations:
    if os.getenv("USER_PRIVATE_SOURCE_INVALIDATIONS") != "true":
        raise ContractError("not_found")
    store = get_resource_store()
    if "K_SERVICE" in os.environ and (
        not isinstance(store, FirestoreUserResourceStore) or store.client._database != "user-data"
    ):
        raise ContractError("authorization_unavailable")
    return SourceInvalidations(store)


@internal.post(PORTFOLIO_FENCE_PATH)
async def invalidate_portfolio_source(
    request: Request,
    response: Response,
    authority: Annotated[SourceInvalidations, Depends(portfolio_invalidation)],
):
    require_portfolio_workload(request)
    value = (await body(request, RootModel[dict[str, object]])).root
    require_selected_private_owner(value.get("ownerSubject"))
    result = await run_in_threadpool(authority.invalidate, value)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-FolioView-Contract"] = CONTRACT_VERSION
    return result


def require_portfolio_workload(request):
    if request.headers.getlist("x-folioview-delegation"):
        raise ContractError("insufficient_scope")
    _require_private_workload(
        request,
        header="authorization",
        audience_env="USER_SERVICE_AUDIENCE",
        caller_env="USER_PRIVATE_PORTFOLIO_CALLER",
    )


@internal.post(PORTFOLIO_REVISION_PATH)
async def acknowledge_portfolio_source_revision(
    request: Request,
    response: Response,
    authority: Annotated[SourceInvalidations, Depends(portfolio_invalidation)],
):
    require_portfolio_workload(request)
    value = await body(request, PortfolioSourceRevision, maximum=4096)
    require_selected_private_owner(value.ownerSubject)
    result = await run_in_threadpool(authority.acknowledge_revision, value)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-FolioView-Contract"] = CONTRACT_VERSION
    return result


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
    require_selected_private_owner(owner_key(uid))
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
    require_selected_private_owner(owner_key(user.uid))
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
    require_selected_private_owner(owner_key(user.uid))
    result = await run_in_threadpool(RegistryHistory(store).page, user.uid, vault_id, value)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-FolioView-Contract"] = CONTRACT_VERSION
    return result


HANDOVER_CHECK_PROFILE = "folioview.owner-handover-check.v1"
HANDOVER_PROFILE = "folioview.owner-handover.v1"
REGISTRY_START_PROFILE = "folioview.owner-registry-start-evidence.v1"


class CutoverScope(ClosedModel):
    contractVersion: Literal[CONTRACT_VERSION]
    ownerSubject: Digest
    vaultId: Identifier


class CutoverCheck(CutoverScope):
    profile: Literal[HANDOVER_CHECK_PROFILE]


class RegistryStartRequest(CutoverScope):
    profile: Literal[REGISTRY_START_PROFILE]
    nonce: OperationId


class PrivateResourceDirectoryRequest(CutoverScope):
    profile: Literal[DIRECTORY_PROFILE]
    nonce: OperationId


def _cutover_scope(value, uid, vault):
    subject = owner_key(uid)
    require_selected_private_owner(subject)
    if value["ownerSubject"] != subject or value["vaultId"] != vault:
        raise ContractError("not_found")


def owner_cutover() -> UserAuthorityCutover:
    if os.getenv("USER_PRIVATE_HANDOVER") != "true":
        raise ContractError("not_found")
    return UserAuthorityCutover(get_resource_store())


def _uncached_private(response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-FolioView-Contract"] = CONTRACT_VERSION


def owner_directory() -> PrivateResourceDirectory:
    if os.getenv("USER_PRIVATE_RESOURCE_DIRECTORY") != "true":
        raise ContractError("not_found")
    return PrivateResourceDirectory(get_resource_store())


@router.post("/{vault_id}/directory/read")
async def read_owner_directory(
    vault_id: str,
    request: Request,
    response: Response,
    user: Annotated[CurrentUser, Depends(require_google_user)],
    directory: Annotated[PrivateResourceDirectory, Depends(owner_directory)],
    _: Annotated[None, Depends(require_owner_proxy)],
):
    value = await body(request, PrivateResourceDirectoryRequest, maximum=4096)
    _cutover_scope(value.model_dump(), user.uid, vault_id)
    result = await run_in_threadpool(directory.read, user.uid, vault_id, value.nonce)
    _uncached_private(response)
    return result


class DisplayNameRead(CutoverScope):
    profile: Literal[DISPLAY_NAME_PROFILE]
    sourceId: Identifier | None
    operationId: OperationId | None


class DisplayNameWrite(CutoverScope):
    profile: Literal[DISPLAY_NAME_PROFILE]
    sourceId: Identifier
    operationId: OperationId
    command: dict


def owner_display_names() -> PrivateDisplayNames:
    if os.getenv("USER_PRIVATE_RESOURCE_DIRECTORY") != "true":
        raise ContractError("not_found")
    return PrivateDisplayNames(get_resource_store())


@router.post("/{vault_id}/display-names/read")
async def read_display_names(
    vault_id: str,
    request: Request,
    response: Response,
    user: Annotated[CurrentUser, Depends(require_google_user)],
    names: Annotated[PrivateDisplayNames, Depends(owner_display_names)],
    _: Annotated[None, Depends(require_owner_proxy)],
):
    value = await body(request, DisplayNameRead, maximum=4096)
    _cutover_scope(value.model_dump(), user.uid, vault_id)
    if value.operationId is not None and value.sourceId is None:
        raise ContractError("malformed_request")
    result = await run_in_threadpool(
        names.read, user.uid, vault_id, value.sourceId, value.operationId
    )
    _uncached_private(response)
    return result


@router.post("/{vault_id}/display-names/write")
async def write_display_name(
    vault_id: str,
    request: Request,
    response: Response,
    user: Annotated[CurrentUser, Depends(require_google_user)],
    names: Annotated[PrivateDisplayNames, Depends(owner_display_names)],
    _: Annotated[None, Depends(require_owner_proxy)],
):
    value = await body(request, DisplayNameWrite, maximum=MAX_DISPLAY_COMMAND_BYTES + 2048)
    _cutover_scope(value.model_dump(), user.uid, vault_id)
    result = await run_in_threadpool(
        names.write, user.uid, vault_id, value.sourceId, value.operationId, value.command
    )
    _uncached_private(response)
    return result


class OwnerCurrentVaultRequest(ClosedModel):
    contractVersion: Literal[CONTRACT_VERSION]
    profile: Literal[OWNER_CURRENT_PROFILE]
    ownerSubject: Digest
    nonce: OperationId


def owner_current_vault() -> PrivateAuthorityViews:
    if os.getenv("USER_PRIVATE_OWNER_CURRENT") != "true":
        raise ContractError("not_found")
    return PrivateAuthorityViews(get_resource_store())


@router.post("/current/read")
async def read_owner_current_vault(
    request: Request,
    response: Response,
    user: Annotated[CurrentUser, Depends(require_google_user)],
    view: Annotated[PrivateAuthorityViews, Depends(owner_current_vault)],
    _: Annotated[None, Depends(require_owner_proxy)],
):
    value = await body(request, OwnerCurrentVaultRequest, maximum=4096)
    subject = owner_key(user.uid)
    require_selected_private_owner(subject)
    if value.ownerSubject != subject:
        raise ContractError("not_found")
    result = await run_in_threadpool(
        view.owner_current, user.uid, value.nonce, now=int(time.time())
    )
    _uncached_private(response)
    return result


@router.post("/{vault_id}/handover/check")
async def check_handover(
    vault_id: str,
    request: Request,
    response: Response,
    user: Annotated[CurrentUser, Depends(require_google_user)],
    cutover: Annotated[UserAuthorityCutover, Depends(owner_cutover)],
    _: Annotated[None, Depends(require_owner_proxy)],
):
    value = await body(request, CutoverCheck)
    _cutover_scope(value.model_dump(), user.uid, vault_id)
    result = await run_in_threadpool(cutover.preflight, user.uid, vault_id, now=int(time.time()))
    _uncached_private(response)
    return {**result, "profile": HANDOVER_CHECK_PROFILE, "ownerSubject": value.ownerSubject}


@router.post("/{vault_id}/handover")
async def install_handover(
    vault_id: str,
    request: Request,
    response: Response,
    user: Annotated[CurrentUser, Depends(require_google_user)],
    cutover: Annotated[UserAuthorityCutover, Depends(owner_cutover)],
    _: Annotated[None, Depends(require_owner_proxy)],
):
    value = (
        await body(request, RootModel[dict[str, object]], maximum=MAX_TRANSITION_PACKET_BYTES + 256)
    ).root
    if (
        value.keys()
        != {
            "contractVersion",
            "profile",
            "ownerSubject",
            "vaultId",
            "operationId",
            "signedTransition",
            "firstBundle",
        }
        or value["profile"] != HANDOVER_PROFILE
        or value["contractVersion"] != CONTRACT_VERSION
    ):
        raise ContractError("malformed_request")
    _cutover_scope(value, user.uid, vault_id)
    packet = {key: value[key] for key in ("operationId", "signedTransition", "firstBundle")}
    result = await run_in_threadpool(
        cutover.install, user.uid, vault_id, packet, now=int(time.time())
    )
    _uncached_private(response)
    return {**result, "contractVersion": CONTRACT_VERSION, "profile": HANDOVER_PROFILE}


@router.post("/{vault_id}/registry-start/read")
async def read_registry_start(
    vault_id: str,
    request: Request,
    response: Response,
    user: Annotated[CurrentUser, Depends(require_google_user)],
    store: Annotated[RecoveryHeads, Depends(owner_recovery_store)],
    _: Annotated[None, Depends(require_owner_proxy)],
):
    value = await body(request, RegistryStartRequest)
    _cutover_scope(value.model_dump(), user.uid, vault_id)
    result = await run_in_threadpool(
        UserAuthorityCutover(store.store).read_start,
        user.uid,
        vault_id,
        value.nonce,
        now=int(time.time()),
    )
    _uncached_private(response)
    return result


class OwnerArchiveLifecycleRead(CutoverScope):
    profile: Literal[ARCHIVE_LIFECYCLE_PROFILE]
    nonce: OperationId
    operationId: OperationId | None


def owner_archive_lifecycle() -> PrivateArchiveLifecycle:
    if os.getenv("USER_PRIVATE_OWNER_CURRENT") != "true":
        raise ContractError("not_found")
    return PrivateArchiveLifecycle(get_resource_store())


@router.post("/{vault_id}/archive-lifecycle/read")
async def read_owner_archive_lifecycle(
    vault_id: str,
    request: Request,
    response: Response,
    user: Annotated[CurrentUser, Depends(require_google_user)],
    lifecycle: Annotated[PrivateArchiveLifecycle, Depends(owner_archive_lifecycle)],
    _: Annotated[None, Depends(require_owner_proxy)],
):
    value = await body(request, OwnerArchiveLifecycleRead, maximum=4096)
    _cutover_scope(value.model_dump(), user.uid, vault_id)
    result = await run_in_threadpool(
        lifecycle.read, user.uid, vault_id, value.nonce, value.operationId
    )
    _uncached_private(response)
    return result


class OwnerArchiveLifecycleAdvance(CutoverScope):
    profile: Literal[ARCHIVE_LIFECYCLE_PROFILE]
    nonce: OperationId
    operationId: OperationId
    command: dict
    archive: dict | None


@router.post("/{vault_id}/archive-lifecycle/advance")
async def advance_owner_archive_lifecycle(
    vault_id: str,
    request: Request,
    response: Response,
    user: Annotated[CurrentUser, Depends(require_google_user)],
    lifecycle: Annotated[PrivateArchiveLifecycle, Depends(owner_archive_lifecycle)],
    _: Annotated[None, Depends(require_owner_proxy)],
):
    if os.getenv("USER_PRIVATE_ARCHIVE_WRITES") != "true":
        raise ContractError("not_found")
    value = await body(request, OwnerArchiveLifecycleAdvance, maximum=MAX_CONTROL_BYTES)
    _cutover_scope(value.model_dump(), user.uid, vault_id)
    receipt = await run_in_threadpool(
        lifecycle.advance, user.uid, vault_id, value.operationId, value.command, value.archive
    )
    _uncached_private(response)
    return {
        "contractVersion": CONTRACT_VERSION,
        "profile": ARCHIVE_LIFECYCLE_PROFILE,
        "ownerSubject": value.ownerSubject,
        "vaultId": vault_id,
        "rootKeyId": receipt["rootKeyId"],
        "nonce": value.nonce,
        "operationId": value.operationId,
        "receipt": receipt,
    }


class OwnerArchiveRemoval(CutoverScope):
    profile: Literal[ARCHIVE_LIFECYCLE_PROFILE]
    nonce: OperationId
    operationId: OperationId
    action: Literal["check", "delete", "withdraw"]
    command: dict
    deletionCommand: dict | None


@router.post("/{vault_id}/archive-lifecycle/removal")
async def owner_archive_removal(
    vault_id: str,
    request: Request,
    response: Response,
    user: Annotated[CurrentUser, Depends(require_google_user)],
    lifecycle: Annotated[PrivateArchiveLifecycle, Depends(owner_archive_lifecycle)],
    _: Annotated[None, Depends(require_owner_proxy)],
):
    if os.getenv("USER_PRIVATE_ARCHIVE_REMOVALS") != "true":
        raise ContractError("not_found")
    value = await body(request, OwnerArchiveRemoval, maximum=MAX_CONTROL_BYTES)
    _cutover_scope(value.model_dump(), user.uid, vault_id)
    if (value.deletionCommand is not None) != (value.action == "withdraw"):
        raise ContractError("malformed_request")
    if value.action == "check":
        result = await run_in_threadpool(
            lifecycle.check_removal, user.uid, vault_id, value.operationId, value.command
        )
    else:
        kind = "archive_delete" if value.action == "delete" else "archive_delete_withdraw"
        receipt = await run_in_threadpool(
            lifecycle.advance,
            user.uid,
            vault_id,
            value.operationId,
            value.command,
            None,
            removal_action=kind,
            deletion=value.deletionCommand,
        )
        result = {
            "contractVersion": CONTRACT_VERSION,
            "profile": receipt["profile"],
            "receipt": receipt,
        }
    _uncached_private(response)
    return {
        "contractVersion": CONTRACT_VERSION,
        "profile": ARCHIVE_LIFECYCLE_PROFILE,
        "ownerSubject": value.ownerSubject,
        "vaultId": vault_id,
        "nonce": value.nonce,
        "operationId": value.operationId,
        "result": result,
    }


HOLDINGS_REGISTRATION_PROFILE = "folioview.owner-holdings-registration.v1"


class HoldingsRegistrationRequest(CutoverScope):
    profile: Literal[HOLDINGS_REGISTRATION_PROFILE]
    sourceId: Identifier
    operationId: OperationId
    command: dict


def owner_holdings_registration() -> HoldingsRegistrations:
    if os.getenv("USER_PRIVATE_SOURCE_REGISTRATIONS") != "true":
        raise ContractError("not_found")
    return HoldingsRegistrations(get_resource_store())


@router.post("/{vault_id}/holdings-sources/{source_id}")
async def register_owner_holdings(
    vault_id: str,
    source_id: str,
    request: Request,
    response: Response,
    user: Annotated[CurrentUser, Depends(require_google_user)],
    registration: Annotated[HoldingsRegistrations, Depends(owner_holdings_registration)],
    _: Annotated[None, Depends(require_owner_proxy)],
):
    value = await body(request, HoldingsRegistrationRequest, maximum=65_536)
    _cutover_scope(value.model_dump(), user.uid, vault_id)
    if value.sourceId != source_id:
        raise ContractError("not_found")
    result = await run_in_threadpool(
        registration.register, user.uid, vault_id, source_id, value.command, value.operationId
    )
    _uncached_private(response)
    return result


OWNER_KEY_RENEWAL_PROFILE = "folioview.owner-user-key-renewal.v1"


class OwnerKeyRenewalRead(CutoverScope):
    profile: Literal[OWNER_KEY_RENEWAL_PROFILE]
    nonce: OperationId
    operationId: OperationId | None


class OwnerKeyRenewalWrite(CutoverScope):
    profile: Literal[OWNER_KEY_RENEWAL_PROFILE]
    nonce: OperationId
    operationId: OperationId
    command: dict
    archiveCommand: dict
    archive: dict
    registryBundle: dict


def owner_key_renewals() -> PrivateKeyRenewals:
    if os.getenv("USER_PRIVATE_OWNER_CURRENT") != "true":
        raise ContractError("not_found")
    return PrivateKeyRenewals(get_resource_store())


def _renewal_reply(value, result, response):
    _uncached_private(response)
    return {
        "contractVersion": CONTRACT_VERSION,
        "profile": OWNER_KEY_RENEWAL_PROFILE,
        "ownerSubject": value.ownerSubject,
        "vaultId": value.vaultId,
        "nonce": value.nonce,
        "operationId": value.operationId,
        "result": result,
    }


@router.post("/{vault_id}/key-renewals/read")
async def read_owner_key_renewal(
    vault_id: str,
    request: Request,
    response: Response,
    user: Annotated[CurrentUser, Depends(require_google_user)],
    service: Annotated[PrivateKeyRenewals, Depends(owner_key_renewals)],
    _: Annotated[None, Depends(require_owner_proxy)],
):
    value = await body(request, OwnerKeyRenewalRead, maximum=4096)
    _cutover_scope(value.model_dump(), user.uid, vault_id)
    if value.operationId is None:
        result = await run_in_threadpool(service.overview, user.uid, vault_id)
    else:
        result = await run_in_threadpool(service.receipt, user.uid, vault_id, value.operationId)
    return _renewal_reply(value, result, response)


@router.post("/{vault_id}/key-renewals/apply")
async def apply_owner_key_renewal(
    vault_id: str,
    request: Request,
    response: Response,
    user: Annotated[CurrentUser, Depends(require_google_user)],
    service: Annotated[PrivateKeyRenewals, Depends(owner_key_renewals)],
    _: Annotated[None, Depends(require_owner_proxy)],
):
    if os.getenv("USER_PRIVATE_KEY_RENEWALS") != "true":
        raise ContractError("not_found")
    value = await body(request, OwnerKeyRenewalWrite, maximum=MAX_REGISTRY_BYTES + 65_536)
    _cutover_scope(value.model_dump(), user.uid, vault_id)
    result = await run_in_threadpool(
        service.renew,
        user.uid,
        vault_id,
        value.operationId,
        value.command,
        value.archiveCommand,
        value.archive,
        value.registryBundle,
    )
    return _renewal_reply(value, result, response)


def owner_registry_writer() -> RegistryUpdates:
    if os.getenv("USER_PRIVATE_REGISTRY_UPDATES") != "true":
        raise ContractError("not_found")
    return RegistryUpdates(get_resource_store())


@router.post("/{vault_id}/registry/advance")
async def advance_owner_registry(
    vault_id: str,
    request: Request,
    response: Response,
    user: Annotated[CurrentUser, Depends(require_google_user)],
    writer: Annotated[RegistryUpdates, Depends(owner_registry_writer)],
    _: Annotated[None, Depends(require_owner_proxy)],
):
    value = await body(request, RegistryUpdate, maximum=MAX_REGISTRY_BYTES + 2_048)
    _cutover_scope(value.model_dump(), user.uid, vault_id)
    result = await run_in_threadpool(writer.update, user.uid, value)
    _uncached_private(response)
    return result


HUB_AUTHORITY_PATH = "/internal/v2/private-resources/hub-authority/read"
PORTFOLIO_AUTHORITY_PATH = "/internal/v2/private-resources/portfolio-authority/read"


def live_authority_views() -> PrivateAuthorityViews:
    if os.getenv("USER_PRIVATE_AUTHORITY_READS") != "true":
        raise ContractError("not_found")
    return PrivateAuthorityViews(get_resource_store())


async def _authority_result(request, response, service, consumer, path, caller_env):
    require_v2(request)
    if request.url.query:
        raise ContractError("unsupported_query")
    authorization = request.headers.getlist("authorization")
    delegation = request.headers.getlist("x-folioview-delegation")
    if len(authorization) != 1 or len(delegation) != 1:
        raise ContractError("invalid_token")
    scheme, _, workload = authorization[0].partition(" ")
    if scheme.lower() != "bearer" or not workload or not delegation[0]:
        raise ContractError("invalid_token")
    audience = os.getenv("USER_SERVICE_AUDIENCE", "")
    verifier = configured_verifier(
        (
            audience,
            audience + path,
            os.getenv("USER_DELEGATION_ISSUER", ""),
            os.getenv(caller_env, ""),
        ),
        path,
    )
    value = (await body(request, RootModel[dict[str, object]], maximum=4096)).root
    try:
        uid = await run_in_threadpool(
            verifier.verify_private_authority_read,
            workload,
            delegation[0],
            request=value,
            consumer=consumer,
        )
    except DelegationError as error:
        code = {
            "invalid_credentials": "invalid_token",
            "permission_denied": "insufficient_scope",
            "verification_unavailable": "authorization_unavailable",
        }[error.code]
        raise ContractError(code) from None
    require_selected_private_owner(owner_key(uid))
    result = await run_in_threadpool(service.lookup, uid, value, now=int(time.time()))
    _uncached_private(response)
    return result


@internal.post(HUB_AUTHORITY_PATH)
async def read_hub_authority(
    request: Request,
    response: Response,
    service: Annotated[PrivateAuthorityViews, Depends(live_authority_views)],
):
    return await _authority_result(
        request, response, service, "hub", HUB_AUTHORITY_PATH, "USER_TRUSTED_HUB_CALLERS"
    )


@internal.post(PORTFOLIO_AUTHORITY_PATH)
async def read_portfolio_authority(
    request: Request,
    response: Response,
    service: Annotated[PrivateAuthorityViews, Depends(live_authority_views)],
):
    return await _authority_result(
        request,
        response,
        service,
        "portfolio",
        PORTFOLIO_AUTHORITY_PATH,
        "USER_PRIVATE_PORTFOLIO_CALLER",
    )
