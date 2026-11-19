"""The optional recovery read projects only current Owner evidence."""

import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from jwcrypto import jwk

from app.main import app
from app.private_resources.api import owner_recovery_store
from app.private_resources.recovery import (
    COLLECTION,
    RecoveryHeads,
    build_recovery_head,
    current_recovery_evidence,
)
from app.resources import FirestoreUserResourceStore, SQLiteUserResourceStore
from folioview_shared.auth import CurrentUser, require_google_user
from folioview_shared.encrypted.authority import verify_registry
from folioview_shared.encrypted.constants import CONTRACT_VERSION
from folioview_shared.encrypted.crypto import jwk_thumbprint, sign_jws
from folioview_shared.encrypted.errors import ContractError
from folioview_shared.encrypted.jsonutil import canonical_json
from folioview_shared.encrypted.private_resources import (
    RECOVERY_PROFILE,
    PrivateRegistryCursor,
    recovery_request_digest,
)
from folioview_shared.identity import owner_key
from folioview_shared.service_identity import UntrustedServiceCaller

UID = "private-recovery-fixture"
OWNER = owner_key(UID)
VAULT = "vault_fixture"
PATH = f"/api/v3/private-resources/vaults/{VAULT}/recovery-evidence"
ARCHIVE = {"state": "active", "version": 4, "digest": "a" * 64}
PROXY_HEADERS = {
    "X-FolioView-Contract": CONTRACT_VERSION,
    "X-FolioView-Proxy-Authorization": "Bearer synthetic_web_workload",
}


def registry_fixture(now=1000, *, signing_keys=None):
    root = jwk.JWK.generate(kty="EC", crv="P-256")
    root_jwk = root.export(private_key=False, as_dict=True)
    scope = {"contractVersion": CONTRACT_VERSION, "ownerSubject": OWNER, "vaultId": VAULT}
    root_id = jwk_thumbprint(root_jwk)
    certificates, descriptions = {}, []
    for role in ("device_sig", "device_enc"):
        key = jwk.JWK.generate(kty="EC", crv="P-256")
        public = key.export(private_key=False, as_dict=True)
        certificate = {
            **scope,
            "artifactType": "key_certificate",
            "certificateId": role,
            "keyId": jwk_thumbprint(public),
            "issuerKeyId": root_id,
            "publicJwk": public,
            "role": role,
            "principalId": "device_fixture",
            "connectionId": None,
            "keyEpoch": 1,
            "notBefore": 200,
            "expiresAt": 1020,
            "capabilities": [],
        }
        if signing_keys is not None:
            signing_keys[role] = key
            if role == "device_sig":
                certificate["capabilities"] = ["control_write", "object_write"]
        certificates[role] = certificate
        descriptions.append(
            {
                "certificateId": role,
                "payloadDigest": hashlib.sha256(canonical_json(certificate)).hexdigest(),
                "active": True,
            }
        )
    checkpoint = {
        **scope,
        "artifactType": "registry_checkpoint",
        "rootKeyId": root_id,
        "rootEpoch": 1,
        "registrySequence": 1,
        "previousDigest": None,
        "entriesDigest": hashlib.sha256(
            canonical_json(sorted(descriptions, key=lambda v: v["certificateId"]))
        ).hexdigest(),
        "keyEpoch": 1,
        "revokedKeyIds": [],
        "issuedAt": 200,
    }
    bundle = {
        "contractVersion": CONTRACT_VERSION,
        "entries": [
            {"certificate": sign_jws(cert, root, typ="fv-control+jws"), "active": True}
            for cert in certificates.values()
        ],
        "checkpoint": sign_jws(checkpoint, root, typ="fv-control+jws"),
    }
    registry = verify_registry(
        bundle,
        root_jwk=root_jwk,
        pinned_root_key_id=root_id,
        owner_subject=OWNER,
        vault_id=VAULT,
        now=now,
    )
    return root, root_jwk, scope, registry, bundle, certificates


def projection(now=1000):
    _, _, scope, registry, _, certificates = registry_fixture(now)
    head = build_recovery_head(
        cursor=PrivateRegistryCursor(registry, 1),
        registry_start=None,
        vault_version=18,
        archive=ARCHIVE,
        sources=[],
        now=now,
    )
    request = {
        **scope,
        "profile": RECOVERY_PROFILE,
        "nonce": "synthetic_recovery_evidence_0001",
        "deviceId": "device_fixture",
        "deviceSigningKeyId": certificates["device_sig"]["keyId"],
        "deviceEncryptionKeyId": certificates["device_enc"]["keyId"],
    }
    return head, request


class RecoveryReadTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.store = SQLiteUserResourceStore(str(Path(temp.name) / "user.sqlite3"))
        self.heads = RecoveryHeads(self.store)
        self.head, self.request = projection()
        self.heads.install(self.head, expected_version=0)

    def test_exact_current_device_nonce_and_expiry_are_bound_in_small_evidence(self):
        result = current_recovery_evidence(self.heads, UID, VAULT, self.request, 1000)
        self.assertEqual(result["requestDigest"], recovery_request_digest(self.request))
        self.assertEqual(result["expiresAt"], 1020)
        self.assertEqual(result["archive"], ARCHIVE)
        self.assertLess(len(canonical_json(result)), 900)
        self.assertFalse({"devices", "registryHistory", "rootJwk"} & result.keys())
        for req, now in (
            (self.request, 1020),
            ({**self.request, "deviceEncryptionKeyId": "x" * 43}, 1000),
            ({**self.request, "deviceId": "other_device"}, 1000),
        ):
            with self.assertRaisesRegex(ContractError, "key_authorization_required"):
                current_recovery_evidence(self.heads, UID, VAULT, req, now)

    def test_replay_fences_and_archive_deletion_preserve_lock(self):
        self.heads.install(self.head, expected_version=0)
        with self.assertRaisesRegex(ContractError, "version_conflict"):
            self.heads.install(
                {**self.head, "vaultVersion": 19, "rootKeyId": "x" * 43}, expected_version=18
            )
        self.heads.install(
            {
                **self.head,
                "vaultVersion": 19,
                "archive": {**ARCHIVE, "version": 5, "state": "deleted"},
            },
            expected_version=18,
        )
        with self.assertRaisesRegex(ContractError, "key_authorization_required"):
            current_recovery_evidence(self.heads, UID, VAULT, self.request, 1000)
        with self.assertRaisesRegex(ContractError, "version_conflict"):
            self.heads.install(self.head, expected_version=19)

    def test_owner_recovery_endpoint_is_opt_in_and_scoped_without_writes(self):
        with TestClient(app) as client:
            self.assertEqual(client.post(PATH, json=self.request).status_code, 401)
            with patch.dict(
                app.dependency_overrides,
                {
                    require_google_user: lambda: CurrentUser(
                        uid=UID, email=None, displayName=None, photoURL=None
                    ),
                },
            ):
                with patch.dict(os.environ, {"USER_PRIVATE_RECOVERY_READ": "false"}):
                    disabled = client.post(PATH, json=self.request)
                self.assertEqual(disabled.status_code, 404)
                with (
                    patch.dict(
                        app.dependency_overrides, {owner_recovery_store: lambda: self.heads}
                    ),
                    patch("app.private_resources.api.time.time", return_value=1000),
                    patch.object(self.heads, "install") as write,
                    patch("app.private_resources.api.configured_owner_proxy") as configure,
                ):
                    bearer = configure.return_value.verify
                    missing = client.post(
                        PATH, json=self.request, headers={"X-FolioView-Contract": CONTRACT_VERSION}
                    )
                    self.assertEqual(missing.status_code, 401)
                    ignored = client.post(
                        PATH + "?owner=foreign", json=self.request, headers=PROXY_HEADERS
                    )
                    self.assertEqual(ignored.status_code, 400)
                    bearer.assert_not_called()
                    response = client.post(PATH, json=self.request, headers=PROXY_HEADERS)
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.headers["cache-control"], "no-store")
                    self.assertEqual(response.headers["x-folioview-contract"], CONTRACT_VERSION)
                    self.assertEqual(response.json()["vaultVersion"], 18)
                    bearer.assert_called_once_with("synthetic_web_workload")
                    for owner in ("foreign", owner_key("another account")):
                        self.assertEqual(
                            client.post(
                                PATH,
                                json={**self.request, "ownerSubject": owner},
                                headers=PROXY_HEADERS,
                            ).status_code,
                            404,
                        )
                    bearer.side_effect = UntrustedServiceCaller
                    refused = client.post(PATH, json=self.request, headers=PROXY_HEADERS)
                    self.assertEqual(refused.status_code, 403)
                write.assert_not_called()


class FirestoreRecoveryTests(unittest.TestCase):
    def test_reads_one_bounded_owner_document_and_install_reuses_user_transaction(self):
        client = MagicMock()
        reference = client.collection.return_value.document.return_value
        reference.get.return_value.exists = False
        with patch("app.resources.firestore.Client", return_value=client):
            heads = RecoveryHeads(FirestoreUserResourceStore("synthetic-project", "user-data"))
        head, request = projection()
        txn = MagicMock()
        with (
            patch(
                "app.private_resources.recovery.firestore.transactional", side_effect=lambda fn: fn
            ),
            patch("app.private_resources.recovery.BoundedTransaction", return_value=txn),
        ):
            heads.install(head, expected_version=0)
        client.collection.assert_called_with(COLLECTION)
        client.collection.return_value.document.assert_called_with(OWNER)
        reference.get.assert_called_once_with(transaction=txn, timeout=4, retry=None)
        txn.set.assert_called_once_with(reference, {"view": canonical_json(head)})
        reference.get.reset_mock()
        reference.get.return_value.exists = True
        reference.get.return_value.to_dict.return_value = {"view": canonical_json(head)}
        self.assertEqual(
            current_recovery_evidence(heads, UID, VAULT, request, 1000)["vaultVersion"], 18
        )
        reference.get.assert_called_once_with(transaction=None, timeout=4, retry=None)
