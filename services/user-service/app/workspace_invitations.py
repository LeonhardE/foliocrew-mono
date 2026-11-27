"""Owner-managed Gmail invitations and retry-safe delivery in User Service."""

import asyncio
import hashlib
import hmac
import os
import re
import time
from collections.abc import Callable
from functools import lru_cache
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from google.cloud import firestore
from pydantic import RootModel
from starlette.concurrency import run_in_threadpool

from folioview_shared.auth import CurrentUser, require_google_user
from folioview_shared.encrypted import CONTRACT_VERSION
from folioview_shared.encrypted.errors import ContractError
from folioview_shared.encrypted.jsonutil import strict_json_loads
from folioview_shared.firestore import BoundedTransaction
from folioview_shared.http import PrivateRoute
from folioview_shared.identity import owner_key

from .private_resources.api import _require_private_workload
from .resource_api import ResourceRoute, body
from .workspace_invite_delivery import DeliveryUnconfirmed, send_invitation

INVITATIONS = "user_workspace_invitations"
MEMBERS = "user_workspace_members"
PAGE_SIZE = 50
INVITATION_LIFETIME = 7 * 24 * 60 * 60
DELIVERY_RETRY_LIFETIME = 23 * 60 * 60
DELIVERY_LEASE = 30
EMAIL = re.compile(r"[a-z0-9]+(?:\.[a-z0-9]+)*@gmail\.com", re.ASCII)
INVITATION_ID = re.compile(r"[0-9a-f]{64}", re.ASCII)
REVISION = re.compile(r"[0-9a-f]{32}", re.ASCII)
router = APIRouter(prefix="/api/v1/workspace-invitations", route_class=PrivateRoute)
internal = APIRouter(prefix="/internal/v2/workspace-invitations", route_class=ResourceRoute)
User = Annotated[CurrentUser, Depends(require_google_user)]


def gmail_address(value: object) -> str:
    if isinstance(value, str) and value.isascii() and len(value) <= 74:
        email = value.strip().lower()
        if EMAIL.fullmatch(email):
            return email
    raise HTTPException(422, "Enter the account’s primary Gmail address.")


def invitation_id(email: str) -> str:
    return hashlib.sha256(email.encode("ascii")).hexdigest()


def can_manage_invitations(user: CurrentUser) -> bool:
    uid = os.environ.get("FOLIOCREW_INVITATION_ADMIN_UID", "")
    return (
        os.environ.get("FOLIOCREW_INVITATIONS_ENABLED") == "1"
        and bool(uid)
        and hmac.compare_digest(uid.encode(), user.uid.encode())
    )


def authorize(user: User) -> CurrentUser:
    if not can_manage_invitations(user):
        raise HTTPException(403, "Invitation administration is unavailable.")
    return user


Admin = Annotated[CurrentUser, Depends(authorize)]


def _checked_id(value: str) -> str:
    if not INVITATION_ID.fullmatch(value):
        raise HTTPException(404, "Invitation unavailable.")
    return value


def _serialize(row: dict, now: int) -> dict:
    status = row["status"]
    if status in ("sending", "send_failed", "invited") and row["expiresAt"] <= now:
        status = "expired"
    return {
        "id": invitation_id(row["email"]),
        "revision": row["deliveryKey"].removeprefix("workspace-invite/"),
        "email": row["email"],
        "status": status,
        "updatedAt": row["updatedAt"],
        "expiresAt": row["expiresAt"],
        "canRetry": status in ("send_failed", "sending")
        and row["leaseUntil"] <= now < row["deliveryStartedAt"] + DELIVERY_RETRY_LIFETIME,
        "canRevoke": status in ("send_failed", "sending", "invited"),
    }


class InvitationStore:
    def __init__(self, client):
        self.client = client
        self.collection = client.collection(INVITATIONS)

    def change(self, key: str, transform: Callable):
        reference = self.collection.document(key)

        @firestore.transactional
        def update(transaction):
            row = reference.get(transaction=transaction, retry=None, timeout=4).to_dict()
            replacement, result = transform(row)
            if replacement is not None:
                transaction.set(reference, replacement)
            return result

        return update(BoundedTransaction(self.client, max_attempts=2))

    def delete_closed(self, key: str, revision: str, now: int) -> None:
        reference = self.collection.document(key)

        @firestore.transactional
        def operation(transaction):
            row = reference.get(transaction=transaction, retry=None, timeout=4).to_dict()
            if row is None:
                return
            current = _serialize(row, now)
            if current["revision"] != revision or current["status"] not in ("revoked", "expired"):
                raise HTTPException(409, "Only the current closed invitation can be deleted.")
            transaction.delete(reference)

        operation(BoundedTransaction(self.client, max_attempts=2))

    def list(self, after: str | None) -> list[dict]:
        query = self.collection.order_by("__name__").limit(PAGE_SIZE + 1)
        if after is not None:
            query = query.start_after({"__name__": self.collection.document(after)})
        return [item.to_dict() for item in query.stream(retry=None, timeout=4)]

    def admit(self, uid: str, google_subject: str, email: str, now: int, *, bind: bool) -> bool:
        membership = self.client.collection(MEMBERS).document(owner_key(uid))
        invitation = self.collection.document(invitation_id(email))

        @firestore.transactional
        def operation(transaction):
            member, invite = [
                ref.get(transaction=transaction, retry=None, timeout=2).to_dict()
                for ref in (membership, invitation)
            ]
            admitted = admission_allowed(member, invite, google_subject, now)
            if admitted and bind and member is None:
                transaction.set(
                    membership,
                    {"googleSubject": google_subject, "state": "active", "joinedAt": now},
                )
                transaction.set(invitation, {**invite, "status": "joined", "updatedAt": now})
            return admitted

        return operation(BoundedTransaction(self.client, max_attempts=2))

    def has_membership(self, uid: str) -> bool:
        member = (
            self.client.collection(MEMBERS)
            .document(owner_key(uid))
            .get(retry=None, timeout=2)
            .to_dict()
        )
        return member is not None and member["state"] == "active"


def admission_allowed(member, invitation, google_subject: str, now: int) -> bool:
    if member is not None:
        return member["state"] == "active" and member["googleSubject"] == google_subject
    return (
        invitation is not None
        and invitation["status"] == "invited"
        and invitation["expiresAt"] > now
    )


@lru_cache(maxsize=2)
def _store(project: str, database: str) -> InvitationStore:
    return InvitationStore(firestore.Client(project=project, database=database))


def get_invitation_store() -> InvitationStore:
    project = os.environ.get("FIREBASE_PROJECT_ID", "")
    database = os.environ.get("FIRESTORE_DATABASE", "")
    if (
        not project
        or database != "user-data"
        or (
            "K_SERVICE" in os.environ
            and (
                os.environ.get("FIRESTORE_EMULATOR_HOST")
                or os.environ.get("FIREBASE_AUTH_EMULATOR_HOST")
            )
        )
    ):
        raise HTTPException(503, "Invitation storage is unavailable.")
    return _store(project, database)


Store = Annotated[InvitationStore, Depends(get_invitation_store)]


def start_delivery(
    row: dict | None, email: str | None, now: int, lease: str, replace_revision: str | None = None
):
    if row is None and email is None:
        raise HTTPException(404, "Invitation unavailable.")
    if row is None and replace_revision is not None:
        raise HTTPException(409, "Invitation has changed. Refresh the list.")
    if row is not None:
        current = _serialize(row, now)
        if email is None:
            if current["revision"] != replace_revision or not current["canRetry"]:
                return None, (row, False)
            replacement = {
                **row,
                "status": "sending",
                "lease": lease,
                "leaseUntil": now + DELIVERY_LEASE,
                "updatedAt": now,
            }
            return replacement, (replacement, True)
        if current["revision"] != replace_revision or current["status"] not in (
            "expired",
            "revoked",
        ):
            return None, (row, False)
    replacement = {
        "email": email,
        "status": "sending",
        "deliveryKey": f"workspace-invite/{lease}",
        "deliveryStartedAt": now,
        "lease": lease,
        "leaseUntil": now + DELIVERY_LEASE,
        "expiresAt": now + INVITATION_LIFETIME,
        "updatedAt": now,
    }
    return replacement, (replacement, True)


def finish_delivery(row: dict | None, lease: str, message_id: str | None, now: int):
    if row is None:
        raise HTTPException(404, "Invitation unavailable.")
    if row["status"] != "sending" or row["lease"] != lease:
        return None, row
    replacement = {
        **row,
        "status": "invited" if message_id else "send_failed",
        "providerMessageId": message_id,
        "leaseUntil": now,
        "updatedAt": now,
    }
    return replacement, replacement


def deliver(
    store: InvitationStore, key: str, email: str | None = None, replace_revision: str | None = None
) -> dict:
    if not os.environ.get("FOLIOCREW_INVITATION_MAIL_KEY"):
        raise HTTPException(503, "Invitation delivery is unavailable.")
    lease = uuid4().hex
    now = int(time.time())
    row, started = store.change(
        key, lambda before: start_delivery(before, email, now, lease, replace_revision)
    )
    if started:
        try:
            message_id = send_invitation(row["email"], row["deliveryKey"])
        except DeliveryUnconfirmed:
            message_id = None
        now = int(time.time())
        row = store.change(key, lambda before: finish_delivery(before, lease, message_id, now))
    return _serialize(row, now)


def revoke(row: dict | None, now: int, revision: str):
    if row is None:
        raise HTTPException(404, "Invitation unavailable.")
    current = _serialize(row, now)
    if current["revision"] != revision or not current["canRevoke"]:
        return None, row
    replacement = {**row, "status": "revoked", "updatedAt": now}
    return replacement, replacement


@router.get("/capability")
def invitation_capability(user: User):
    return {"canManageInvitations": can_manage_invitations(user)}


@router.get("")
def list_invitations(admin: Admin, store: Store, after: str | None = None):
    rows = store.list(_checked_id(after) if after is not None else None)
    now = int(time.time())
    items = [_serialize(row, now) for row in rows[:PAGE_SIZE]]
    return {"items": items, "nextCursor": items[-1]["id"] if len(rows) > PAGE_SIZE else None}


async def read_invitation_request(request: Request) -> tuple[str, str | None]:
    if (
        request.headers.get("content-type", "").partition(";")[0].strip().lower()
        != "application/json"
    ):
        raise HTTPException(415, "Expected JSON.")
    raw = bytearray()
    try:
        async with asyncio.timeout(5):
            async for chunk in request.stream():
                if len(raw) + len(chunk) > 512:
                    raise HTTPException(413, "Invitation request is too large.")
                raw.extend(chunk)
        payload = strict_json_loads(bytes(raw), max_bytes=512)
    except (ContractError, TimeoutError, ValueError) as error:
        raise HTTPException(422, "Invalid invitation request.") from error
    if type(payload) is not dict or set(payload) not in ({"email"}, {"email", "replaceRevision"}):
        raise HTTPException(422, "Invalid invitation request.")
    revision = payload.get("replaceRevision")
    if "replaceRevision" in payload and (
        not isinstance(revision, str) or not REVISION.fullmatch(revision)
    ):
        raise HTTPException(422, "Invalid invitation revision.")
    return gmail_address(payload["email"]), revision


@router.post("")
async def create_invitation(request: Request, admin: Admin, store: Store):
    email, revision = await read_invitation_request(request)
    return await run_in_threadpool(deliver, store, invitation_id(email), email, revision)


@router.post("/{key}/{revision}/retry")
def retry_invitation(key: str, revision: str, admin: Admin, store: Store):
    if not REVISION.fullmatch(revision):
        raise HTTPException(404, "Invitation unavailable.")
    return deliver(store, _checked_id(key), replace_revision=revision)


@router.post("/{key}/{revision}/revoke")
def revoke_invitation(key: str, revision: str, admin: Admin, store: Store):
    if not REVISION.fullmatch(revision):
        raise HTTPException(404, "Invitation unavailable.")
    now = int(time.time())
    return _serialize(store.change(_checked_id(key), lambda row: revoke(row, now, revision)), now)


@router.delete("/{key}/{revision}", status_code=204)
def delete_closed_invitation(key: str, revision: str, admin: Admin, store: Store):
    if not REVISION.fullmatch(revision):
        raise HTTPException(404, "Invitation unavailable.")
    store.delete_closed(_checked_id(key), revision, int(time.time()))
    return Response(status_code=204)


@router.get("/workspace-access")
def workspace_access(user: User):
    configured = os.environ.get("FOLIOCREW_WORKSPACE_ACCESS_RESTRICTED") == "1"
    return {
        "restricted": configured,
        "admitted": not configured
        or can_manage_invitations(user)
        or get_invitation_store().has_membership(user.uid),
    }


def require_workspace_member(user: User) -> None:
    if not workspace_access(user)["admitted"]:
        raise HTTPException(403, "A workspace invitation is required.")


@internal.post("/{action}")
async def assess_sign_in(request: Request, response: Response, action: Literal["check", "bind"]):
    if os.environ.get("FOLIOCREW_INVITATIONS_ENABLED") != "1":
        raise ContractError("not_found")
    _require_private_workload(
        request,
        header="authorization",
        audience_env="USER_SERVICE_AUDIENCE",
        caller_env="USER_INVITATION_AUTH_CALLER",
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-FolioView-Contract"] = CONTRACT_VERSION
    event = (await body(request, RootModel[dict[str, object]], maximum=1024)).root
    if (
        set(event) != {"contractVersion", "uid", "email", "emailVerified", "provider", "subject"}
        or event["contractVersion"] != CONTRACT_VERSION
        or event["provider"] != "google.com"
        or event["emailVerified"] is not True
        or any(
            not isinstance(event[field], str)
            or not 1 <= len(event[field]) <= 128
            or not event[field].isascii()
            or any(character.isspace() for character in event[field])
            for field in ("uid", "subject")
        )
    ):
        raise ContractError("insufficient_scope")
    user = CurrentUser(uid=event["uid"], email=None, displayName=None, photoURL=None)
    if can_manage_invitations(user):
        return {"admitted": True}
    try:
        email = gmail_address(event["email"])
    except HTTPException:
        raise ContractError("insufficient_scope") from None
    admitted = await run_in_threadpool(
        get_invitation_store().admit,
        user.uid,
        event["subject"],
        email,
        int(time.time()),
        bind=action == "bind",
    )
    return {"admitted": admitted}
