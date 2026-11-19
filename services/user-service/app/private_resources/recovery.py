"""Store the bounded current recovery projection alongside User's existing data."""

from typing import Annotated, Literal

from google.cloud import firestore
from pydantic import BaseModel, ConfigDict, Field

from folioview_shared.encrypted.constants import (
    CONTRACT_VERSION,
    MAX_CONTEXT_BYTES,
    MAX_SAFE_INTEGER,
)
from folioview_shared.encrypted.errors import ContractError
from folioview_shared.encrypted.jsonutil import canonical_json, strict_json_loads
from folioview_shared.encrypted.private_resources import (
    RECOVERY_EVIDENCE_SECONDS,
    RECOVERY_PROFILE,
    PrivateRegistryCursor,
    recovery_request_digest,
    source_index_digest,
    verify_owner_recovery_evidence,
)
from folioview_shared.firestore import BoundedTransaction
from folioview_shared.identity import owner_key

from ..resources import FirestoreUserResourceStore, ResourceUnavailable, SQLiteUserResourceStore

COLLECTION = "user_private_recovery_heads"
Version = Annotated[int, Field(ge=1, le=MAX_SAFE_INTEGER)]
EpochSeconds = Annotated[int, Field(ge=0, le=MAX_SAFE_INTEGER)]
Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
KeyId = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{43}$")]
Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")]
OperationId = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{22,128}$")]


class ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class RegistryHead(ClosedModel):
    registryEpoch: Version
    registrySequence: Version
    checkpointDigest: Digest
    keyEpoch: Version


class ArchiveBoundary(ClosedModel):
    state: Literal["active", "revoking", "deleted"]
    version: Version
    digest: Digest


class DevicePair(ClosedModel):
    deviceId: Identifier
    deviceSigningKeyId: KeyId
    deviceEncryptionKeyId: KeyId
    notBefore: EpochSeconds
    expiresAt: EpochSeconds


class AuthorityHandover(ClosedModel):
    """Service-side proof reference installed with a scoped authoritative head."""

    operationId: OperationId
    baselineDigest: Digest
    writerEpoch: Version


class CurrentHead(ClosedModel):
    ownerSubject: Identifier
    vaultId: Identifier
    rootKeyId: KeyId
    vaultVersion: Version
    registry: RegistryHead
    registryStart: RegistryHead | None
    archive: ArchiveBoundary
    sourcesDigest: Digest
    devices: Annotated[list[DevicePair], Field(max_length=32)]
    handover: AuthorityHandover | None = None


class RecoveryRequest(ClosedModel):
    contractVersion: Literal[CONTRACT_VERSION]
    profile: Literal[RECOVERY_PROFILE]
    ownerSubject: Identifier
    vaultId: Identifier
    nonce: str
    deviceId: Identifier
    deviceSigningKeyId: KeyId
    deviceEncryptionKeyId: KeyId


def build_recovery_head(
    *,
    cursor: PrivateRegistryCursor,
    registry_start: dict | None,
    vault_version: int,
    archive: dict,
    sources: list[dict],
    now: int,
) -> dict:
    """Project a registry that the writer has already verified to its current head."""
    registry = cursor.registry
    devices = {}
    for key in sorted(registry.active_key_ids):
        role = registry.certificates[key]["role"]
        if role not in {"device_sig", "device_enc"}:
            continue
        try:
            certificate = registry.cert(key, role=role, connection_id=None, now=now)
        except ContractError as error:
            if error.code != "key_authorization_required":
                raise
            continue
        devices.setdefault(certificate["principalId"], {})[role] = certificate
    pairs = []
    for principal, keys in sorted(devices.items()):
        if keys.keys() != {"device_sig", "device_enc"}:
            continue
        signing, encryption = keys["device_sig"], keys["device_enc"]
        pairs.append(
            {
                "deviceId": principal,
                "deviceSigningKeyId": signing["keyId"],
                "deviceEncryptionKeyId": encryption["keyId"],
                "notBefore": max(signing["notBefore"], encryption["notBefore"]),
                "expiresAt": min(signing["expiresAt"], encryption["expiresAt"]),
            }
        )
    head = CurrentHead(
        ownerSubject=registry.owner_subject,
        vaultId=registry.vault_id,
        rootKeyId=registry.root_key_id,
        vaultVersion=vault_version,
        registry=cursor.head(),
        registryStart=registry_start,
        archive=archive,
        sourcesDigest=source_index_digest(sources),
        devices=pairs,
    ).model_dump(exclude_unset=True)
    if len(canonical_json(head)) > MAX_CONTEXT_BYTES:
        raise ContractError("payload_too_large")
    return head


class RecoveryHeads:
    """Store a same-account compare-and-set projection, using the User database."""

    def __init__(self, store):
        self.store = store
        if isinstance(store, SQLiteUserResourceStore):
            with store.connection() as db:
                db.execute(
                    f"CREATE TABLE IF NOT EXISTS {COLLECTION} "
                    "(owner TEXT PRIMARY KEY, value TEXT NOT NULL)"
                )

    @staticmethod
    def _decode(value):
        if value is None:
            return None
        try:
            return CurrentHead.model_validate(
                strict_json_loads(value, max_bytes=MAX_CONTEXT_BYTES)
            ).model_dump(exclude_unset=True)
        except (ContractError, TypeError, ValueError):
            raise ContractError("authorization_unavailable") from None

    def _reference(self, owner):
        if isinstance(self.store, FirestoreUserResourceStore):
            return self.store.client.collection(COLLECTION).document(owner)
        raise ContractError("authorization_unavailable")

    @staticmethod
    def _local(db, owner):
        row = db.execute(f"SELECT value FROM {COLLECTION} WHERE owner=?", (owner,)).fetchone()
        return row[0] if row else None

    @staticmethod
    def _firestore(reference, transaction=None):
        snapshot = reference.get(transaction=transaction, timeout=4, retry=None)
        if not snapshot.exists:
            return None
        document = snapshot.to_dict()
        if (
            type(document) is not dict
            or document.keys() != {"view"}
            or type(document["view"]) is not bytes
        ):
            raise ContractError("authorization_unavailable")
        return document["view"]

    def read(self, owner):
        if isinstance(self.store, SQLiteUserResourceStore):
            with self.store.connection() as db:
                raw = self._local(db, owner)
            return self._decode(raw)
        return self._decode(self._firestore(self._reference(owner)))

    def install(self, head, *, expected_version):
        """Accept an already verified projection from the same transaction boundary."""
        if type(head) is not dict:
            raise ContractError("malformed_request")
        candidate = self._decode(canonical_json(head))
        owner = candidate["ownerSubject"]

        def check(raw):
            previous = self._decode(raw)
            if previous == candidate:
                return False
            if previous is None:
                if expected_version != 0:
                    raise ContractError("version_conflict")
                return True
            if (
                previous["vaultVersion"] != expected_version
                or candidate["vaultVersion"] <= expected_version
                or any(previous[key] != candidate[key] for key in ("vaultId", "rootKeyId"))
                or previous.get("handover") != candidate.get("handover")
            ):
                raise ContractError("version_conflict")
            prior, next_head = previous["registry"], candidate["registry"]
            clocks = ("registryEpoch", "registrySequence", "keyEpoch")
            if (
                any(next_head[clock] < prior[clock] for clock in clocks)
                or (
                    next_head["registrySequence"] == prior["registrySequence"]
                    and next_head != prior
                )
                or (
                    next_head["registryEpoch"] == prior["registryEpoch"]
                    and candidate["registryStart"] != previous["registryStart"]
                )
                or candidate["archive"]["version"] < previous["archive"]["version"]
            ):
                raise ContractError("version_conflict")
            return True

        if isinstance(self.store, SQLiteUserResourceStore):
            try:
                with self.store.connection() as db:
                    db.execute("BEGIN IMMEDIATE")
                    if check(self._local(db, owner)):
                        db.execute(
                            f"INSERT INTO {COLLECTION}(owner,value) VALUES (?,?) "
                            "ON CONFLICT(owner) DO UPDATE SET value=excluded.value",
                            (owner, canonical_json(candidate).decode()),
                        )
            except ResourceUnavailable as error:
                if isinstance(error.__cause__, ContractError):
                    raise error.__cause__ from None
                raise ContractError("authorization_unavailable") from None
            return

        reference = self._reference(owner)

        @firestore.transactional
        def write(transaction):
            if check(self._firestore(reference, transaction)):
                transaction.set(reference, {"view": canonical_json(candidate)})

        write(BoundedTransaction(self.store.client, max_attempts=2))


def current_recovery_evidence(heads: RecoveryHeads, uid: str, vault: str, request: dict, now: int):
    digest = recovery_request_digest(request)
    owner = owner_key(uid)
    if request["ownerSubject"] != owner or request["vaultId"] != vault:
        raise ContractError("not_found")
    head = heads.read(owner)
    if head is None or head["ownerSubject"] != owner or head["vaultId"] != vault:
        raise ContractError("not_found")
    matched = next(
        (
            pair
            for pair in head["devices"]
            if all(
                pair[key] == request[key]
                for key in ("deviceId", "deviceSigningKeyId", "deviceEncryptionKeyId")
            )
            and pair["notBefore"] <= now < pair["expiresAt"]
        ),
        None,
    )
    if matched is None or head["archive"]["state"] != "active":
        raise ContractError("key_authorization_required")
    result = {
        "contractVersion": CONTRACT_VERSION,
        "profile": RECOVERY_PROFILE,
        "requestDigest": digest,
        "device": "active",
        "verifiedAt": now,
        "expiresAt": min(now + RECOVERY_EVIDENCE_SECONDS, matched["expiresAt"]),
        **{key: value for key, value in head.items() if key not in {"devices", "handover"}},
    }
    return verify_owner_recovery_evidence(
        result, request=request, pinned_root_key_id=head["rootKeyId"], now=now
    )
