"""A new signed registry must anchor the owner, old chain, and existing archive."""

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
from jwcrypto import jwk
from test_private_recovery import OWNER, UID, VAULT, registry_fixture

from app.main import app
from app.private_resources.api import HANDOVER_CHECK_PROFILE, HANDOVER_PROFILE, owner_cutover
from app.private_resources.authority_cutover import HANDOVERS, WITNESSES, UserAuthorityCutover
from app.private_resources.legacy_baselines import LegacyVaultBaselines, verified_baseline
from app.private_resources.original_operations import original_operation_baseline
from app.private_resources.recovery import RecoveryHeads
from app.private_resources.registry_pages import COLLECTION, RegistryHistory, RegistryPageRequest
from app.private_resources.registry_transition import UserRegistryTransition
from app.private_resources.report_sources import HOLDINGS_FENCES, holdings_fence_key
from app.private_resources.source_invalidations import SOURCE_INDEX, SourceInvalidations
from app.private_resources.source_registrations import SOURCE_REGISTRATIONS, HoldingsRegistrations
from app.resources import SQLiteUserResourceStore
from folioview_shared.auth import CurrentUser, require_google_user
from folioview_shared.encrypted.authority import verify_registry
from folioview_shared.encrypted.constants import CONTRACT_VERSION
from folioview_shared.encrypted.crypto import jwk_thumbprint, sign_jws, verify_jws
from folioview_shared.encrypted.errors import ContractError
from folioview_shared.encrypted.jsonutil import b64url_encode, canonical_json
from folioview_shared.encrypted.private_resources import PrivateRegistryCursor


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
        self.service = UserRegistryTransition(self.store)

    def sign(self, value):
        return sign_jws(value, self.root, typ="fv-control+jws")

    def test_signatures_validate_without_changing_active_state(self):
        accepted = self.service.verify_candidate(UID, VAULT, self.digest, self.packet, now=1000)
        self.assertEqual(accepted["registryStart"], self.transition["nextHead"])
        self.assertEqual(accepted["operationId"], self.packet["operationId"])
        self.assertEqual(
            self.service.verify_candidate(UID, VAULT, self.digest, self.packet, now=1000), accepted
        )
        self.assertIsNone(self.heads.read(OWNER))

    def test_well_signed_wrong_archive_unknown_owner_and_missing_original_history_are_refused(self):
        changed = self.sign(
            {**self.transition, "archive": {**self.transition["archive"], "digest": "f" * 64}}
        )
        with self.assertRaisesRegex(ContractError, "version_conflict"):
            self.service.verify_candidate(
                UID, VAULT, self.digest, {**self.packet, "signedTransition": changed}, now=1000
            )
        with self.assertRaisesRegex(ContractError, "not_found"):
            self.service.verify_candidate("foreign", VAULT, self.digest, self.packet, now=1000)
        with self.store.connection() as db:
            db.execute(f"DELETE FROM {COLLECTION}")
        with self.assertRaisesRegex(ContractError, "authorization_unavailable"):
            self.service.verify_candidate(UID, VAULT, self.digest, self.packet, now=1000)

    def stage_frozen_scope(self, *, extra_operations=None, **changes):
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

    def test_atomic_install_requires_frozen_account_and_keeps_original_receipt(self):
        cutover = UserAuthorityCutover(self.store)
        with self.assertRaisesRegex(ContractError, "source_unavailable"):
            cutover.install(UID, VAULT, self.packet, now=1000)
        self.stage_frozen_scope(activeLegacyAgents=1)
        with self.assertRaisesRegex(ContractError, "source_unavailable"):
            cutover.install(UID, VAULT, self.packet, now=1000)
        self.assertIsNone(self.heads.read(OWNER))
        self.stage_frozen_scope()

        accepted = cutover.install(UID, VAULT, self.packet, now=1000)
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

        self.assertEqual(cutover.install(UID, VAULT, self.packet, now=9000), accepted)
        with self.assertRaisesRegex(ContractError, "idempotency_conflict"):
            cutover.install(
                UID,
                VAULT,
                {**self.packet, "operationId": "synthetic_changed_operation_001"},
                now=1000,
            )

    def test_offline_owner_can_page_only_the_signed_original_target(self):
        cutover = UserAuthorityCutover(self.store)
        self.stage_frozen_scope()
        cutover.install(UID, VAULT, self.packet, now=1000)
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

    def test_conflict_or_receipt_failure_leaves_every_authority_record_unpublished(self):
        cutover = UserAuthorityCutover(self.store)
        self.stage_frozen_scope(tombstonesDigest="f" * 64)
        with self.assertRaisesRegex(ContractError, "version_conflict"):
            cutover.install(UID, VAULT, self.packet, now=1000)
        self.stage_frozen_scope()
        with self.store.connection() as db:
            db.execute(
                f"CREATE TRIGGER fail_handover BEFORE INSERT ON {HANDOVERS} "
                "BEGIN SELECT RAISE(ABORT, 'synthetic transaction failure'); END"
            )
        with self.assertRaisesRegex(ContractError, "authorization_unavailable"):
            cutover.install(UID, VAULT, self.packet, now=1000)
        self.assertIsNone(self.heads.read(OWNER))
        with self.store.connection() as db:
            self.assertEqual(db.execute(f"SELECT COUNT(*) FROM {HANDOVERS}").fetchone(), (0,))
            self.assertEqual(db.execute(f"SELECT COUNT(*) FROM {COLLECTION}").fetchone(), (1,))

    def test_original_terminal_ack_is_installed_for_exact_portfolio_retry(self):
        cutover = UserAuthorityCutover(self.store)
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
        self.assertEqual(cutover.install(UID, VAULT, packet, now=1000)["nextVaultVersion"], 3)
        writer = SourceInvalidations(self.store)
        self.assertEqual(writer.invalidate(old), ack)
        with self.assertRaisesRegex(ContractError, "idempotency_conflict"):
            writer.invalidate({**old, "reason": "disconnected"})

    def test_owner_routes_bind_both_authorities_and_keep_review_read_only(self):
        cutover = UserAuthorityCutover(self.store)
        self.stage_frozen_scope()
        path = f"/api/v3/private-resources/vaults/{VAULT}/handover"
        scope = {"contractVersion": CONTRACT_VERSION, "ownerSubject": OWNER, "vaultId": VAULT}
        header = {
            "X-FolioView-Contract": CONTRACT_VERSION,
            "X-FolioView-Proxy-Authorization": "Bearer synthetic_workload",
        }
        verifier = Mock()
        with (
            TestClient(app) as client,
            patch.dict(
                app.dependency_overrides,
                {
                    require_google_user: lambda: CurrentUser(
                        uid=UID, email=None, displayName=None, photoURL=None
                    )
                },
            ),
            patch("app.private_resources.api.configured_owner_proxy", return_value=verifier),
            patch("app.private_resources.api.time.time", return_value=1000),
        ):
            ready = {**scope, "profile": HANDOVER_CHECK_PROFILE}
            with patch.dict("os.environ", {"USER_PRIVATE_HANDOVER": "false"}):
                self.assertEqual(
                    client.post(path + "/check", headers=header, json=ready).status_code, 404
                )
            with patch.dict(app.dependency_overrides, {owner_cutover: lambda: cutover}):
                missing = client.post(
                    path + "/check", json=ready, headers={"X-FolioView-Contract": CONTRACT_VERSION}
                )
                self.assertEqual(missing.status_code, 401, missing.text)
                other = client.post(
                    path + "/check", headers=header, json={**ready, "ownerSubject": "a" * 64}
                )
                self.assertEqual(other.status_code, 404, other.text)
                checked = client.post(path + "/check", headers=header, json=ready)
                self.assertEqual(checked.status_code, 200, checked.text)
                self.assertEqual(checked.json()["status"], "ready")
                self.assertIsNone(self.heads.read(OWNER))
                request = {**scope, "profile": HANDOVER_PROFILE, **self.packet}
                closed = client.post(path, headers=header, json={**request, "prf": "forbidden"})
                self.assertEqual(closed.status_code, 400, closed.text)
                self.assertIsNone(self.heads.read(OWNER))
                receipt = client.post(path, headers=header, json=request)
                self.assertEqual(receipt.status_code, 200, receipt.text)
                self.assertEqual(receipt.headers["cache-control"], "no-store")
                self.assertEqual(receipt.json()["operationId"], self.packet["operationId"])
                confirmed = client.post(path + "/check", headers=header, json=ready)
                self.assertEqual(confirmed.status_code, 200, confirmed.text)
                self.assertEqual(confirmed.json()["status"], "installed")

    def test_ten_retired_registrations_leave_capacity_for_a_new_signed_source(self):
        cutover = UserAuthorityCutover(self.store)
        self.stage_frozen_scope()
        cutover.install(UID, VAULT, self.packet, now=1000)
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

        def command(source_name, operation_id, head):
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

        with self.assertRaisesRegex(ContractError, "rollback_detected"):
            auth.register(
                UID,
                VAULT,
                source,
                command(source, operation, self.transition["previousHead"]),
                operation,
            )
        signed = command(source, operation, target)
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
                UID, VAULT, "retired_0", command("retired_0", new_operation, target), new_operation
            )
