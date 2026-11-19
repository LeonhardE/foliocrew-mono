"""Exercise staged original bundles and authenticated fixed-target pagination."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from test_private_recovery import ARCHIVE, OWNER, UID, VAULT, registry_fixture

from app.main import app
from app.private_resources.api import owner_recovery_store
from app.private_resources.recovery import RecoveryHeads, build_recovery_head
from app.private_resources.registry_pages import PROFILE, RegistryHistory, RegistryPageRequest
from app.resources import SQLiteUserResourceStore
from folioview_shared.auth import CurrentUser, require_google_user
from folioview_shared.encrypted.authority import verify_registry
from folioview_shared.encrypted.constants import CONTRACT_VERSION
from folioview_shared.encrypted.crypto import sign_jws, verify_jws
from folioview_shared.encrypted.errors import ContractError
from folioview_shared.encrypted.private_resources import (
    PrivateRegistryCursor,
    verify_private_registry_page,
)

PATH = f"/api/v3/private-resources/vaults/{VAULT}/registry-pages/read"


class RegistryPageTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.heads = RecoveryHeads(SQLiteUserResourceStore(str(Path(temporary.name) / "user.db")))
        self.history = RegistryHistory(self.heads)
        self.root, self.public, _, self.start, self.bundle, _ = registry_fixture()
        self.expected = {
            "root_jwk": self.public,
            "pinned_root_key_id": self.start.root_key_id,
            "owner_subject": OWNER,
            "vault_id": VAULT,
            "now": 1000,
        }

    def stage(self, count):
        bundles = [self.bundle]
        registry = self.start
        self.history.stage(
            self.bundle, root_jwk=self.public, cursor=PrivateRegistryCursor(registry, 1)
        )
        for sequence in range(2, count + 1):
            checkpoint = verify_jws(bundles[-1]["checkpoint"], self.public, typ="fv-control+jws")
            checkpoint.update(
                registrySequence=sequence,
                issuedAt=200 + sequence,
                previousDigest=registry.checkpoint_digest,
            )
            bundle = {
                **bundles[-1],
                "checkpoint": sign_jws(checkpoint, self.root, typ="fv-control+jws"),
            }
            registry = verify_registry(bundle, **self.expected, previous=registry)
            bundles.append(bundle)
            self.history.stage(
                bundle, root_jwk=self.public, cursor=PrivateRegistryCursor(registry, 1)
            )
        return bundles, PrivateRegistryCursor(registry, 1)

    def install(self, cursor):
        head = build_recovery_head(
            cursor=cursor,
            registry_start=None,
            vault_version=40,
            archive=ARCHIVE,
            sources=[],
            now=1000,
        )
        self.heads.install(head, expected_version=0)

    @staticmethod
    def request(target, base=None, **overrides):
        return {
            "contractVersion": CONTRACT_VERSION,
            "profile": PROFILE,
            "ownerSubject": OWNER,
            "vaultId": VAULT,
            "base": base,
            "target": target,
            **overrides,
        }

    def test_original_bundles_page_across_32_and_verify_against_one_fixed_target(self):
        originals, end = self.stage(33)
        self.install(end)
        target = end.head()
        collected, previous = [], None
        while previous is None or previous.head() != target:
            base = previous.head() if previous else None
            spec = RegistryPageRequest.model_validate(self.request(target, base))
            page = self.history.page(UID, VAULT, spec)
            self.assertEqual(page["base"], base)
            self.assertEqual(page["target"], target)
            collected.extend(page["bundles"])
            previous = verify_private_registry_page(
                page,
                **self.expected,
                trusted_target=target,
                previous=previous,
            )
            self.assertLessEqual(len(collected), len(originals))
        self.assertEqual(collected, originals)

    def test_mismatched_base_and_target_are_refused_without_returning_a_partial_page(self):
        _, cursor = self.stage(5)
        self.install(cursor)
        target = cursor.head()
        base = {**PrivateRegistryCursor(self.start, 1).head(), "checkpointDigest": "f" * 64}
        for dto in (self.request(target, base), self.request({**target, "keyEpoch": 2})):
            with self.assertRaisesRegex(ContractError, "registry_conflict"):
                self.history.page(UID, VAULT, RegistryPageRequest.model_validate(dto))

    def test_identical_bundle_retry_is_safe_and_resigned_different_bytes_keep_original(self):
        first = PrivateRegistryCursor(self.start, 1)
        self.history.stage(self.bundle, root_jwk=self.public, cursor=first)
        self.history.stage(self.bundle, root_jwk=self.public, cursor=first)
        original = self.bundle["checkpoint"]
        claims = verify_jws(original, self.public, typ="fv-control+jws")
        other = {**self.bundle, "checkpoint": sign_jws(claims, self.root, typ="fv-control+jws")}
        self.assertNotEqual(other, self.bundle)
        with self.assertRaisesRegex(ContractError, "registry_conflict"):
            self.history.stage(other, root_jwk=self.public, cursor=first)
        self.install(first)
        request = RegistryPageRequest.model_validate(self.request(first.head()))
        self.assertEqual(self.history.page(UID, VAULT, request)["bundles"], [self.bundle])

    def test_route_uses_verified_owner_and_current_target(self):
        _, end = self.stage(5)
        self.install(end)
        request = self.request(end.head())
        with TestClient(app) as client:
            self.assertEqual(client.post(PATH, json=request).status_code, 401)
            with patch.dict(
                app.dependency_overrides,
                {
                    require_google_user: lambda: CurrentUser(
                        uid=UID,
                        email=None,
                        displayName=None,
                        photoURL=None,
                    ),
                    owner_recovery_store: lambda: self.heads,
                },
            ):
                response = client.post(PATH, json=request)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers["cache-control"], "no-store")
                self.assertEqual(len(response.json()["bundles"]), 4)
                self.assertEqual(
                    client.post(
                        PATH, json={**request, "ownerSubject": "another_owner"}
                    ).status_code,
                    404,
                )
