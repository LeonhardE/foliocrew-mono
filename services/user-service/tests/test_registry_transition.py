"""A new signed registry must anchor the owner, old chain, and existing archive."""

import hashlib
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from jwcrypto import jwk
from test_private_recovery import OWNER, UID, VAULT, registry_fixture

from app.main import app
from app.private_resources.authority_cutover import (
    HANDOVERS,
    WITNESSES,
    CutoverReceipt,
    UserAuthorityCutover,
)
from app.private_resources.legacy_baselines import LegacyVaultBaselines, verified_baseline
from app.private_resources.original_operations import (
    original_fence_receipts,
    original_operation_baseline,
)
from app.private_resources.recovery import COLLECTION as HEADS
from app.private_resources.recovery import RecoveryHeads, build_recovery_head
from app.private_resources.registry_pages import (
    COLLECTION,
    ORIGINAL_HEAD_PROFILE,
    OriginalRegistryHeadRequest,
    RegistryHistory,
    RegistryPageRequest,
    _index,
)
from app.private_resources.registry_retention import (
    ARCHIVE_HOLDER,
    RegistryRetention,
    RetiredRegistryScope,
)
from app.private_resources.report_sources import HOLDINGS_FENCES, holdings_fence_key
from app.private_resources.source_invalidations import (
    INVALIDATION_RECEIPTS,
    SOURCE_INDEX,
    SourceInvalidations,
)
from app.private_resources.source_registrations import SOURCE_REGISTRATIONS, HoldingsRegistrations
from app.resources import SQLiteUserResourceStore
from folioview_shared.encrypted.authority import verify_registry
from folioview_shared.encrypted.constants import CONTRACT_VERSION
from folioview_shared.encrypted.crypto import (
    jwk_thumbprint,
    sign_jws,
    signing_input_fingerprint,
    verify_jws,
)
from folioview_shared.encrypted.errors import ContractError
from folioview_shared.encrypted.jsonutil import b64url_encode, canonical_json, strict_json_loads
from folioview_shared.encrypted.private_resources import (
    PrivateRegistryCursor,
    verify_private_registry_transition,
)


def digest(value):
    return hashlib.sha256(canonical_json(value)).hexdigest()


class RegistryTransitionTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.store = SQLiteUserResourceStore(str(Path(folder.name) / "original.sqlite"))
        self.signing_keys = {}
        self.root, public, scope, base, bundle, _ = registry_fixture(signing_keys=self.signing_keys)
        self.scope = {"ownerSubject": OWNER, "vaultId": VAULT, "rootKeyId": base.root_key_id}
        recovery = jwk.JWK.generate(kty="EC", crv="P-256").export(private_key=False, as_dict=True)
        certificate = {
            **scope,
            "artifactType": "key_certificate",
            "certificateId": "recovery_fixture",
            "keyId": jwk_thumbprint(recovery),
            "issuerKeyId": base.root_key_id,
            "publicJwk": recovery,
            "role": "recovery_enc",
            "principalId": "recovery_fixture",
            "connectionId": None,
            "keyEpoch": 1,
            "notBefore": 200,
            "expiresAt": 1020,
            "capabilities": [],
        }
        bundle["entries"].append({"certificate": self.sign(certificate), "active": True})
        checkpoint = verify_jws(bundle["checkpoint"], public, typ="fv-control+jws")
        descriptions = []
        for entry in bundle["entries"]:
            prior = verify_jws(entry["certificate"], public, typ="fv-control+jws")
            descriptions.append(
                {
                    "certificateId": prior["certificateId"],
                    "payloadDigest": digest(prior),
                    "active": True,
                }
            )
        checkpoint["entriesDigest"] = digest(
            sorted(descriptions, key=lambda row: row["certificateId"])
        )
        bundle["checkpoint"] = self.sign(checkpoint)
        args = dict(
            root_jwk=public,
            pinned_root_key_id=base.root_key_id,
            owner_subject=OWNER,
            vault_id=VAULT,
            now=1000,
        )
        original = verify_registry(bundle, **args)
        previous = PrivateRegistryCursor(original, 1)
        self.heads = RecoveryHeads(self.store)
        RegistryHistory(self.heads).stage(bundle, root_jwk=public, cursor=previous)
        archive = {
            **self.scope,
            "profile": "folioview.passkey-vault.v1",
            "credentialId": b64url_encode(b"existing-fake-credential"),
            "prfSalt": b64url_encode(b"b" * 32),
            "iv": b64url_encode(b"c" * 12),
            "ciphertext": b64url_encode(b"synthetic-encrypted-original"),
        }
        vault = {
            **self.scope,
            "rootJwk": public,
            "registryHistory": [bundle],
            "archive": archive,
            "version": 1,
            "operationCount": 1,
            "sources": [],
        }
        self.vault = vault
        prepared = verified_baseline(OWNER, vault, None, now=1000)
        self.digest = hashlib.sha256(prepared).hexdigest()
        LegacyVaultBaselines(self.store).stage(
            OWNER, vault, None, expected_digest=self.digest, now=1000
        )
        new_bundle = {
            **bundle,
            "checkpoint": self.sign(
                {
                    **checkpoint,
                    "registrySequence": 2,
                    "previousDigest": original.checkpoint_digest,
                    "issuedAt": 1000,
                }
            ),
        }
        current = verify_registry(new_bundle, **args, previous=original)
        self.transition = {
            **self.scope,
            "contractVersion": CONTRACT_VERSION,
            "profile": "folioview.owner-registry-transition.v1",
            "operationId": "synthetic_registry_transition_0001",
            "previousVaultVersion": 1,
            "nextVaultVersion": 2,
            "previousHead": previous.head(),
            "nextHead": PrivateRegistryCursor(current, 2).head(),
            "ownerKeyIds": sorted(current.active_key_ids),
            "issuedAt": 1000,
            "archive": {"state": "active", "version": 1, "digest": digest(archive)},
        }
        self.packet = {
            "operationId": self.transition["operationId"],
            "signedTransition": self.sign(self.transition),
            "firstBundle": new_bundle,
        }

    def sign(self, value):
        return sign_jws(value, self.root, typ="fv-control+jws")

    def stage_frozen_scope(self, *, extra_operations=None, **changes):
        UserAuthorityCutover(self.store)
        key = digest([OWNER, "bootstrap", "synthetic_original_bootstrap_001"])
        fields = {
            "ownerSubject": {"stringValue": OWNER},
            "kind": {"stringValue": "bootstrap"},
            "fingerprint": {"stringValue": "0" * 64},
        }
        operations = {"hub_operations/" + key: fields, **(extra_operations or {})}
        body = original_operation_baseline(OWNER, self.vault, operations)
        receipt_digest = hashlib.sha256(body).hexdigest()
        LegacyVaultBaselines(self.store).stage_original_operations(
            OWNER, self.vault, operations, expected_digest=receipt_digest
        )
        witness = {
            **self.scope,
            "writerEpoch": 2,
            "freezeId": "synthetic_hub_writer_freeze_001",
            "baselineDigest": self.digest,
            "operationsDigest": receipt_digest,
            "tombstonesDigest": digest([]),
            "activeLegacyAgents": 0,
            "unsettledLegacyOperations": 0,
            **changes,
        }
        with self.store.connection() as db:
            db.execute(
                f"INSERT OR REPLACE INTO {WITNESSES} VALUES (?, ?)",
                (OWNER, canonical_json(witness).decode()),
            )
        return witness

    def stage_transferred_authority(self, packet=None):
        packet = self.packet if packet is None else packet
        authority = UserAuthorityCutover(self.store)
        witness = authority._read(((WITNESSES, OWNER),))[0]
        baseline = authority.verifier.baselines.read(OWNER, VAULT, witness["baselineDigest"])
        original = strict_json_loads(baseline)
        public = original["rootJwk"]
        signed = packet["signedTransition"]
        candidate = verify_jws(signed, public, typ="fv-control+jws")
        previous, _, _ = authority.verifier.original_history(original, 1000)
        start = verify_private_registry_transition(
            signed,
            first_bundle=packet["firstBundle"],
            root_jwk=public,
            owner_subject=OWNER,
            vault_id=VAULT,
            pinned_root_key_id=self.scope["rootKeyId"],
            authenticated_start=candidate["nextHead"],
            previous=previous,
            now=1000,
        )
        first = start.head()
        boundary = {
            "operationId": packet["operationId"],
            "baselineDigest": witness["baselineDigest"],
            "writerEpoch": 2,
        }
        receipt = CutoverReceipt.model_validate(
            {
                **self.scope,
                **boundary,
                "transitionFingerprint": signing_input_fingerprint(signed),
                "nextVaultVersion": candidate["nextVaultVersion"],
                "registryStart": first,
            }
        ).model_dump()
        view = build_recovery_head(
            cursor=start,
            registry_start=first,
            vault_version=receipt["nextVaultVersion"],
            archive=original["archiveBoundary"],
            sources=[],
            now=1000,
        )
        view["handover"] = boundary
        old_operations = authority.verifier.baselines.read(
            OWNER, VAULT, witness["operationsDigest"]
        )
        initial = {
            (HEADS, OWNER): view,
            (HANDOVERS, OWNER): {
                "packetDigest": digest(packet),
                "freezeId": witness["freezeId"],
                "signedTransition": signed,
                "receipt": receipt,
            },
            (COLLECTION, _index(OWNER, VAULT, first["registryEpoch"], first["registrySequence"])): {
                "head": first,
                "bundle": packet["firstBundle"],
                "rootJwk": public,
            },
            (SOURCE_INDEX, OWNER): {"ownerSubject": OWNER, "vaultId": VAULT, "entries": []},
            **{
                (INVALIDATION_RECEIPTS, key): row
                for key, row in original_fence_receipts(original, old_operations).items()
            },
        }
        authority._transaction(lambda _read, create: create(initial), writes=True)
        return receipt

    def test_existing_authority_preserves_the_signed_start_and_original_receipt(self):
        cutover = UserAuthorityCutover(self.store)
        self.stage_frozen_scope()
        accepted = self.stage_transferred_authority()
        self.assertEqual(accepted["registryStart"], self.transition["nextHead"])
        self.assertEqual(accepted["writerEpoch"], 2)
        head = self.heads.read(OWNER)
        self.assertEqual(head["registry"], accepted["registryStart"])
        self.assertEqual(head["registryStart"], accepted["registryStart"])
        self.assertEqual(head["sourcesDigest"], digest([]))
        self.assertEqual(head["handover"]["operationId"], accepted["operationId"])
        sequence = accepted["registryStart"]["registrySequence"]
        stored = RegistryHistory(self.heads)._read(head, 2, [sequence])
        self.assertEqual(stored[0]["bundle"], self.packet["firstBundle"])
        nonce = "synthetic_browser_cold_nonce_001"
        start = cutover.read_start(UID, VAULT, nonce, now=1001)
        self.assertEqual(start["nonce"], nonce)
        self.assertEqual(start["registry"], accepted["registryStart"])
        self.assertEqual(start["signedTransition"], self.packet["signedTransition"])
        self.assertEqual(start["firstBundle"], self.packet["firstBundle"])
        with self.assertRaisesRegex(ContractError, "not_found"):
            cutover.read_start("another-account", VAULT, nonce, now=1001)

    def test_registry_retention_derives_and_persists_only_the_authenticated_original_scope(self):
        self.stage_frozen_scope()
        self.stage_transferred_authority()
        ledger = RegistryRetention(self.store)
        scope = RetiredRegistryScope(**self.scope, registryEpoch=1)
        expected = {
            "registryEpoch": 1,
            "retiredEntries": 1,
            "protectedEntries": 1,
            "deletableEntries": 0,
            "references": 1,
            "coverageComplete": False,
        }
        self.assertEqual(ledger.audit_original(UID, VAULT, now=1001), expected)
        self.assertEqual(ledger._record(scope)["references"], {})
        for _ in range(2):
            self.assertEqual(
                ledger.audit_original(UID, VAULT, now=1001, record_reference=True), expected
            )
        persisted = RegistryRetention(self.store)
        (proof,) = persisted._record(scope)["references"].values()
        self.assertEqual(proof["holderId"], ARCHIVE_HOLDER)
        with self.assertRaisesRegex(ContractError, "version_conflict"):
            persisted.release(scope, proof)
        with self.assertRaisesRegex(ContractError, "not_found"):
            persisted.audit_original("unrelated-account", VAULT, now=1001, record_reference=True)
        self.assertEqual(
            RegistryHistory(self.heads)._read(self.scope, 1, [1])[0]["bundle"],
            self.vault["registryHistory"][0],
        )

    def test_registry_retention_serializes_registrations_and_rejects_late_replays(self):
        ledger = RegistryRetention(self.store)
        scope = RetiredRegistryScope(**self.scope, registryEpoch=1)
        first = {
            **scope.model_dump(),
            "contractVersion": CONTRACT_VERSION,
            "profile": "folioview.private-history-reference.v1",
            "holderId": "hub",
            "referenceId": "frozen_run_1",
            "purpose": "frozen_run",
            "firstSequence": 1,
            "lastSequence": 1,
        }
        second = {**first, "referenceId": "frozen_run_2"}
        with ThreadPoolExecutor(max_workers=2) as pool:
            tuple(pool.map(lambda reference: ledger.register(scope, reference), (first, second)))
        ledger.register(scope, first)
        self.assertEqual(len(ledger._record(scope)["references"]), 2)
        with self.assertRaisesRegex(ContractError, "recipient_binding_mismatch"):
            ledger.release(scope.model_copy(update={"ownerSubject": "f" * 64}), first)
        with self.assertRaisesRegex(ContractError, "version_conflict"):
            ledger.release(scope, {**first, "lastSequence": 2})
        ledger.release(scope, first)
        ledger.release(scope, first)
        with self.assertRaisesRegex(ContractError, "version_conflict"):
            ledger.register(scope, first)
        self.assertEqual(list(ledger._record(scope)["references"].values()), [second])

    def test_offline_owner_can_page_only_the_signed_original_target(self):
        self.stage_frozen_scope()
        self.stage_transferred_authority()
        history = RegistryHistory(self.heads)
        target = self.transition["previousHead"]
        request = {
            "contractVersion": CONTRACT_VERSION,
            "profile": "folioview.owner-registry-page.v1",
            "ownerSubject": OWNER,
            "vaultId": VAULT,
            "base": None,
            "target": target,
        }
        page = history.page(UID, VAULT, RegistryPageRequest.model_validate(request))
        self.assertEqual(page["target"], target)
        self.assertEqual(page["bundles"], self.vault["registryHistory"])
        self.assertEqual(self.heads.read(OWNER)["registry"], self.transition["nextHead"])
        for mismatch in (
            {**target, "checkpointDigest": "1" * 64},
            {**target, "registrySequence": target["registrySequence"] + 1},
        ):
            with self.assertRaisesRegex(ContractError, "registry_conflict"):
                history.page(
                    UID, VAULT, RegistryPageRequest.model_validate({**request, "target": mismatch})
                )
        with self.assertRaisesRegex(ContractError, "not_found"):
            history.page("unrelated-owner", VAULT, RegistryPageRequest.model_validate(request))

    def test_original_head_read_returns_only_the_root_anchored_terminal_bundle(self):
        self.stage_frozen_scope()
        self.stage_transferred_authority()
        history = RegistryHistory(self.heads)
        target = self.transition["previousHead"]
        request = OriginalRegistryHeadRequest(
            contractVersion=CONTRACT_VERSION,
            profile=ORIGINAL_HEAD_PROFILE,
            ownerSubject=OWNER,
            vaultId=VAULT,
            target=target,
        )
        with patch.object(history, "_read", wraps=history._read) as read:
            proof = history.original_head(UID, VAULT, request)
            self.assertEqual(proof["target"], target)
            self.assertEqual(proof["bundle"], self.vault["registryHistory"][-1])
            self.assertEqual(read.call_args.args[1:], (1, [target["registrySequence"]]))
        with self.assertRaisesRegex(ContractError, "not_found"):
            history.original_head("unrelated-owner", VAULT, request)
        with self.assertRaisesRegex(ContractError, "registry_conflict"):
            history.original_head(
                UID,
                VAULT,
                request.model_copy(
                    update={
                        "target": request.target.model_copy(update={"checkpointDigest": "a" * 64})
                    }
                ),
            )
        route = f"/api/v3/private-resources/vaults/{VAULT}/original-registry-head/read"
        with TestClient(app) as client:
            self.assertEqual(client.post(route, json=request.model_dump()).status_code, 401)

    def test_original_terminal_ack_serves_exact_portfolio_retry(self):
        ref = {
            "kind": "holdings",
            "sourceService": "portfolio",
            "resourceId": "retired_holding_fixture",
            "incarnation": "retired_fixture_incarnation",
        }
        self.vault.update(
            version=2, operationCount=2, sources=[{"resourceRef": ref, "sourceEpoch": 1}]
        )
        prepared = verified_baseline(OWNER, self.vault, None, now=1000)
        self.digest = hashlib.sha256(prepared).hexdigest()
        LegacyVaultBaselines(self.store).stage(
            OWNER, self.vault, None, expected_digest=self.digest, now=1000
        )
        packet = {
            **self.packet,
            "signedTransition": self.sign(
                {**self.transition, "previousVaultVersion": 2, "nextVaultVersion": 3}
            ),
        }
        old = {
            "contractVersion": CONTRACT_VERSION,
            "ownerSubject": OWNER,
            "mutationId": "synthetic_old_delete_operation_01",
            "ref": ref,
            "expectedSourceEpoch": 1,
            "newSourceEpoch": 2,
            "reason": "deleted",
        }
        ack = {
            "contractVersion": CONTRACT_VERSION,
            "mutationId": old["mutationId"],
            "ref": ref,
            "acknowledgedSourceEpoch": 2,
            "acknowledgedAt": "1970-01-01T00:08:20Z",
        }
        fence = {
            "ownerSubject": OWNER,
            "vaultId": VAULT,
            "binding": {"ref": ref, "sourceEpoch": 2},
            "state": "deleted",
            "currentRevision": 0,
        }

        def field(value):
            if type(value) is int:
                return {"integerValue": str(value)}
            if type(value) is dict:
                return {"mapValue": {"fields": {k: field(v) for k, v in value.items()}}}
            return {"stringValue": value}

        operation_key = digest([OWNER, "portfolio", old["mutationId"]])
        self.stage_frozen_scope(
            extra_operations={
                "hub_fence_mutations/" + operation_key: {
                    k: field(v)
                    for k, v in {"request": old, "fingerprint": digest(old), "ack": ack}.items()
                }
            },
            tombstonesDigest=digest([fence]),
        )
        key = holdings_fence_key(OWNER, VAULT, ref["resourceId"])
        with self.store.connection() as db:
            db.execute(
                f"INSERT INTO {HOLDINGS_FENCES} VALUES (?, ?)",
                (key, canonical_json(fence).decode()),
            )
        self.assertEqual(self.stage_transferred_authority(packet)["nextVaultVersion"], 3)
        writer = SourceInvalidations(self.store)
        self.assertEqual(writer.invalidate(old), ack)
        with self.assertRaisesRegex(ContractError, "idempotency_conflict"):
            writer.invalidate({**old, "reason": "disconnected"})

    def test_retired_handover_paths_are_absent_even_with_the_previous_flag(self):
        with TestClient(app) as client, patch.dict("os.environ", {"USER_PRIVATE_HANDOVER": "true"}):
            path = f"/api/v3/private-resources/vaults/{VAULT}/handover"
            self.assertEqual(client.post(path, json=self.packet).status_code, 404)
            self.assertEqual(client.post(path + "/check", json={}).status_code, 404)
        self.assertIsNone(self.heads.read(OWNER))

    def signed_registration(self, source_name, operation_id, head):
        return sign_jws(
            {
                "contractVersion": CONTRACT_VERSION,
                "ownerSubject": OWNER,
                "vaultId": VAULT,
                "artifactType": "control_command",
                "stableOperationId": operation_id,
                "action": "manual_source_create",
                "targetId": source_name,
                "expectedVersion": 0,
                "expectedSourceEpoch": None,
                "parameters": {},
                "registrySequence": head["registrySequence"],
                "checkpointDigest": head["checkpointDigest"],
                "keyEpoch": head["keyEpoch"],
            },
            self.signing_keys["device_sig"],
            typ="fv-control+jws",
        )

    def test_delete_releases_one_of_ten_current_slots_and_old_command_cannot_revive_it(self):
        self.stage_frozen_scope()
        self.stage_transferred_authority()
        writer = HoldingsRegistrations(self.store, clock=lambda: 1000)
        target = self.transition["nextHead"]

        def register(number):
            source = f"holdings_number_{number}"
            operation = f"synthetic_registration_number_{number}"
            signed = self.signed_registration(source, operation, target)
            return (UID, VAULT, source, signed, operation)

        first = register(0)
        admitted = writer.register(*first)
        for number in range(1, 10):
            writer.register(*register(number))
        next_command = register(10)
        with self.assertRaisesRegex(ContractError, "version_conflict"):
            writer.register(*next_command)
        SourceInvalidations(self.store, clock=lambda: 1001).invalidate(
            {
                "contractVersion": CONTRACT_VERSION,
                "ownerSubject": OWNER,
                "mutationId": "synthetic_retirement_number_zero",
                "ref": admitted["source"]["resourceRef"],
                "expectedSourceEpoch": 1,
                "newSourceEpoch": 2,
                "reason": "deleted",
            }
        )
        writer.register(*next_command)
        self.assertEqual(writer.register(*first), admitted)
        with self.store.connection() as db:
            entries = self.store.value(db, SOURCE_INDEX, OWNER)["entries"]
        self.assertEqual(len(entries), 10)
        self.assertNotIn(first[2], [item["binding"]["ref"]["resourceId"] for item in entries])
        self.assertIn(next_command[2], [item["binding"]["ref"]["resourceId"] for item in entries])

    def test_ten_retired_registrations_leave_capacity_for_a_new_signed_source(self):
        self.stage_frozen_scope()
        self.stage_transferred_authority()
        for number in range(10):
            ref = {
                "kind": "holdings",
                "sourceService": "portfolio",
                "resourceId": f"retired_{number}",
                "incarnation": f"retired_instance_{number}",
            }
            fence = {
                "ownerSubject": OWNER,
                "vaultId": VAULT,
                "binding": {"ref": ref, "sourceEpoch": 2},
                "state": "deleted",
                "currentRevision": 0,
            }
            with self.store.connection() as db:
                db.execute(
                    f"INSERT INTO {HOLDINGS_FENCES} VALUES (?, ?)",
                    (
                        holdings_fence_key(OWNER, VAULT, ref["resourceId"]),
                        canonical_json(fence).decode(),
                    ),
                )
        auth = HoldingsRegistrations(self.store, clock=lambda: 1000)
        source = "new_holdings_fixture"
        operation = "synthetic_holdings_registration_01"
        target = self.transition["nextHead"]

        with self.assertRaisesRegex(ContractError, "rollback_detected"):
            auth.register(
                UID,
                VAULT,
                source,
                self.signed_registration(source, operation, self.transition["previousHead"]),
                operation,
            )
        signed = self.signed_registration(source, operation, target)
        first = auth.register(UID, VAULT, source, signed, operation)
        self.assertEqual(first["source"]["sourceEpoch"], 1)
        self.assertEqual(auth.register(UID, VAULT, source, signed, operation), first)
        self.assertEqual(self.heads.read(OWNER)["vaultVersion"], 3)
        with self.store.connection() as db:
            self.assertEqual(
                db.execute(f"SELECT COUNT(*) FROM {HOLDINGS_FENCES}").fetchone(), (11,)
            )
            self.assertEqual(
                db.execute(f"SELECT COUNT(*) FROM {SOURCE_REGISTRATIONS}").fetchone(), (1,)
            )
            index = self.store.value(db, SOURCE_INDEX, OWNER)
        self.assertEqual(
            [row["binding"]["ref"]["resourceId"] for row in index["entries"]], [source]
        )
        with self.assertRaisesRegex(ContractError, "version_conflict"):
            new_operation = "synthetic_holdings_registration_02"
            auth.register(
                UID,
                VAULT,
                "retired_0",
                self.signed_registration("retired_0", new_operation, target),
                new_operation,
            )
