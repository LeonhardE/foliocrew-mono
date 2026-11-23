"""Separate bootstrap-only OAuth; real Authlib, synthetic accounts and credentials."""

import copy
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock
from urllib.parse import parse_qsl, urlsplit

from fixtures import BOOT, OTHER_UID, UID, VaultFixture
from test_oauth import CALLBACK, CLIENT, VERIFIER, authorization_params, configuration

from app.agent_credentials import AgentCredentialService
from app.native_credentials import NativeCredentialService
from app.native_origin import BRAND_ORIGIN, BRAND_RESOURCE
from app.native_transport import (
    PROFILE,
    REFRESH_IDLE_SECONDS,
    SCOPE,
    NativeConnectionOwnerService,
    NativeTransportService,
)
from app.oauth import OAuthFailure, OAuthService
from app.oauth_config import Client, digest
from app.store import SQLiteHubStore, document_path, private_resource_writer_fence_path
from app.user_vault_authority import CurrentUserVault, ScopedUserVaults
from app.vaults import VaultService
from folioview_shared.encrypted.errors import ContractError
from folioview_shared.encrypted.private_resources import PrivateRegistryCursor

BROWSER = "b" * 43


class NativeTransportTests(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.store = SQLiteHubStore(Path(scratch.name) / "native.sqlite3")
        self.now = 1000
        self.f = VaultFixture()
        VaultService(self.store, clock=lambda: self.now).bootstrap(UID, self.f.bootstrap(), BOOT)
        self.service = NativeTransportService(self.store, configuration(), clock=lambda: self.now)
        self.authorize_params = authorization_params(
            scope=SCOPE, resource=self.service.config.resource
        )

    def authorize(self, uid=UID):
        request = self.service.authorize(copy.deepcopy(self.authorize_params), BROWSER)
        callback = self.service.approve(uid, request, BROWSER, self.f.vault)
        fields = dict(parse_qsl(urlsplit(callback).query))
        return request, callback, fields["code"]

    def exchange(self, code):
        return self.service.protocol(
            {
                "grant_type": "authorization_code",
                "client_id": CLIENT,
                "code": code,
                "redirect_uri": CALLBACK,
                "code_verifier": VERIFIER,
                "resource": self.service.config.resource,
            },
            {},
            "token",
        )

    def connect(self):
        _, _, code = self.authorize()
        status, tokens, _ = self.exchange(code)
        self.assertEqual(status, 200)
        return tokens

    def test_same_provider_on_both_origins_keeps_the_legacy_connection_and_issuer(self):
        legacy = self.connect()
        config = configuration()
        branded = NativeTransportService(
            self.store,
            replace(config, issuer=BRAND_ORIGIN, consent_url=BRAND_ORIGIN + "/oauth/consent"),
            primary_issuer=config.issuer,
            clock=lambda: self.now,
        )
        params = authorization_params(scope=SCOPE, resource=BRAND_RESOURCE)
        request = branded.authorize(params, BROWSER)
        callback = branded.approve(UID, request, BROWSER, self.f.vault)
        code = dict(parse_qsl(urlsplit(callback).query))["code"]
        form = {
            "grant_type": "authorization_code",
            "client_id": CLIENT,
            "code": code,
            "redirect_uri": CALLBACK,
            "code_verifier": VERIFIER,
            "resource": BRAND_RESOURCE,
        }
        self.assertEqual(self.exchange(code)[0], 400)
        status, tokens, _ = branded.protocol(form, {}, "token")
        self.assertEqual(status, 200)
        first = self.service.authenticate(legacy["access_token"])
        second = branded.authenticate(tokens["access_token"])
        self.assertNotEqual(first.connection_id, second.connection_id)
        for service, token in (
            (branded, legacy["access_token"]),
            (self.service, tokens["access_token"]),
        ):
            with self.assertRaises(OAuthFailure):
                service.authenticate(token)
        refreshed = {}
        for service, other, previous in (
            (self.service, branded, legacy),
            (branded, self.service, tokens),
        ):
            form = {
                "grant_type": "refresh_token",
                "client_id": CLIENT,
                "refresh_token": previous["refresh_token"],
            }
            self.assertEqual(
                other.protocol({**form, "resource": other.config.resource}, {}, "token")[0],
                400,
            )
            status, rotated, _ = service.protocol(
                {**form, "resource": service.config.resource}, {}, "token"
            )
            self.assertEqual(status, 200)
            refreshed[service.config.resource] = rotated["access_token"]
        native_credentials = NativeCredentialService(
            branded, owner_url="https://owner.example/agents"
        )
        prepared = native_credentials.prepare(refreshed[BRAND_RESOURCE])
        owner_credentials = AgentCredentialService(
            self.store, audience=config.issuer, client_ids=[CLIENT], clock=lambda: self.now
        )
        opened = owner_credentials.owner_setup(
            UID, self.f.vault, second.connection_id, prepared["setup"]["setupIntentId"]
        )
        self.assertEqual(prepared["issuer"], BRAND_ORIGIN)
        self.assertEqual(opened["issuer"], BRAND_ORIGIN)
        self.assertIsNone(opened["predecessorConnectionId"])

    def test_frozen_owner_cannot_enroll_exchange_or_refresh_and_can_still_disconnect(self):
        tokens = self.connect()
        active = self.service.authenticate(tokens["access_token"])
        approved, callback, unused_code = self.authorize()
        pending = self.service.authorize(copy.deepcopy(self.authorize_params), BROWSER)
        marker = document_path("hub_private_resource_writer_fences", self.f.owner)
        self.store.transact(lambda unit: unit.put(marker, {"state": "frozen"}))
        with self.assertRaisesRegex(ContractError, "authorization_unavailable"):
            self.service.approve(UID, pending, BROWSER, self.f.vault)
        self.assertEqual(self.service.approve(UID, approved, BROWSER, self.f.vault), callback)
        self.assertEqual(self.exchange(unused_code)[0], 400)
        with self.assertRaises(OAuthFailure):
            self.service.authenticate(tokens["access_token"])
        response = self.service.protocol(
            {
                "grant_type": "refresh_token",
                "client_id": CLIENT,
                "resource": self.service.config.resource,
                "refresh_token": tokens["refresh_token"],
            },
            {},
            "token",
        )
        self.assertEqual(response[0], 400)
        management = NativeConnectionOwnerService(self.store, clock=lambda: self.now)
        self.assertEqual(
            management.native_disconnect(UID, active.connection_id)["connection"]["status"],
            "revoked",
        )

        unrelated = VaultFixture(OTHER_UID)
        VaultService(self.store, clock=lambda: self.now).bootstrap(
            OTHER_UID, unrelated.bootstrap(), BOOT
        )
        ident = self.service.authorize(copy.deepcopy(self.authorize_params), BROWSER)
        result = self.service.approve(OTHER_UID, ident, BROWSER, unrelated.vault)
        self.assertEqual(self.exchange(dict(parse_qsl(urlsplit(result).query))["code"])[0], 200)

    def test_transferred_link_refreshes_and_original_credentials_stay_retired(self):
        old = self.connect()
        original = self.service.authenticate(old["access_token"])
        approved, previous_callback, old_code = self.authorize()
        marker = private_resource_writer_fence_path(self.f.owner)
        transferred = {
            "ownerSubject": self.f.owner,
            "vaultId": self.f.vault,
            "state": "transferred",
            "writerEpoch": 2,
            "rootKeyId": self.f.root_id,
            "transitionFingerprint": "a" * 64,
        }
        self.store.transact(lambda unit: unit.put(marker, transferred))
        client = Mock()
        client.read.return_value = CurrentUserVault(
            {"ownerSubject": self.f.owner},
            PrivateRegistryCursor(self.f.registry, 2),
            transferred,
            self.now + 8,
        )
        self.service.user_vaults = ScopedUserVaults(self.store, owner=self.f.owner, client=client)
        self.assertEqual(
            self.service.approve(UID, approved, BROWSER, self.f.vault), previous_callback
        )
        client.read.assert_not_called()
        self.assertEqual(self.exchange(old_code)[0], 400)
        with self.assertRaises(OAuthFailure):
            self.service.authenticate(old["access_token"])

        def refresh(token):
            return self.service.protocol(
                {
                    "grant_type": "refresh_token",
                    "client_id": CLIENT,
                    "resource": self.service.config.resource,
                    "refresh_token": token,
                },
                {},
                "token",
            )

        self.assertEqual(refresh(old["refresh_token"])[0], 400)
        issued = self.connect()
        client.read.assert_called_once_with(UID, self.f.vault, transferred)
        latest = self.service.authenticate(issued["access_token"])
        self.assertNotEqual(latest.connection_id, original.connection_id)
        status, rotated, _ = refresh(issued["refresh_token"])
        self.assertEqual(status, 200)
        self.assertEqual(
            self.service.authenticate(rotated["access_token"]).connection_id, latest.connection_id
        )
        self.store.transact(
            lambda unit: unit.put(marker, {**transferred, "transitionFingerprint": "b" * 64})
        )
        self.assertEqual(refresh(rotated["refresh_token"])[0], 400)
        with self.assertRaises(OAuthFailure):
            self.service.authenticate(rotated["access_token"])

    def test_native_records_follow_the_issuing_resource_on_shared_storage(self):
        origin = "https://second-hub.example"
        second_client = Client("second_chat", [CALLBACK], provider="chatgpt")
        config = replace(configuration(), clients=(*configuration().clients, second_client))
        other = NativeTransportService(
            self.store,
            replace(config, issuer=origin, consent_url=origin + "/oauth/consent"),
            clock=lambda: self.now,
        )
        request = self.service.authorize(self.authorize_params, BROWSER)
        with self.assertRaises(ContractError):
            other.pending(UID, request, BROWSER)
        self.assertEqual(self.service.pending(UID, request, BROWSER)["requestId"], request)
        _, _, code = self.authorize()

        def read_record(service, table, token):
            path = document_path(table, digest(token))
            return service.transact(lambda unit: unit.get(path))

        self.assertIsNone(read_record(other, "hub_oauth_codes", code))
        self.assertFalse(read_record(self.service, "hub_oauth_codes", code)["used"])
        status, tokens, _ = self.exchange(code)
        self.assertEqual(status, 200)
        for field, table in [
            ("access_token", "hub_oauth_access"),
            ("refresh_token", "hub_oauth_refresh"),
        ]:
            self.assertIsNone(read_record(other, table, tokens[field]))
            self.assertEqual(
                read_record(self.service, table, tokens[field])["resource"],
                self.service.config.resource,
            )
        second_request = other.authorize(
            authorization_params(
                client_id=second_client.client_id, scope=SCOPE, resource=other.config.resource
            ),
            BROWSER,
        )
        callback = other.approve(UID, second_request, BROWSER, self.f.vault)
        second_code = dict(parse_qsl(urlsplit(callback).query))["code"]
        status, second_tokens, _ = other.protocol(
            {
                "grant_type": "authorization_code",
                "client_id": second_client.client_id,
                "code": second_code,
                "redirect_uri": CALLBACK,
                "code_verifier": VERIFIER,
                "resource": other.config.resource,
            },
            {},
            "token",
        )
        self.assertEqual(status, 200)
        self.assertEqual(
            other.authenticate(second_tokens["access_token"]).owner_subject, self.f.owner
        )
        self.assertIsNone(
            read_record(self.service, "hub_oauth_access", second_tokens["access_token"])
        )
        self.assertEqual(self.refresh(tokens["refresh_token"])[0], 200)

    def refresh(self, token):
        return self.service.protocol(
            {
                "grant_type": "refresh_token",
                "client_id": CLIENT,
                "refresh_token": token,
                "resource": self.service.config.resource,
            },
            {},
            "token",
        )

    def test_metadata_and_actual_code_exchange_are_bootstrap_only(self):
        self.assertEqual(self.service.metadata()["scopes_supported"], [SCOPE])
        self.assertEqual(
            self.service.metadata()["issuer"], configuration().issuer + "/oauth/persistent"
        )
        tokens = self.connect()
        p = self.service.authenticate(tokens["access_token"])
        self.assertEqual(tokens["scope"], SCOPE)
        self.assertEqual(p.owner_subject, self.f.owner)
        self.assertEqual(p.vault_id, self.f.vault)
        self.assertEqual(tokens["expires_in"], 600)
        self.assertFalse(hasattr(self.service, "authorize_in_transaction"))

    def test_pending_is_cookie_and_google_owner_bound_and_creates_no_resource_authority(self):
        request = self.service.authorize(self.authorize_params, BROWSER)
        state = self.service.pending(UID, request, BROWSER)
        self.assertEqual(state["profile"], PROFILE)
        self.assertEqual(state["authority"], "account_link_only")
        callback = self.service.approve(UID, request, BROWSER, self.f.vault)
        self.assertEqual(self.service.approve(UID, request, BROWSER, self.f.vault), callback)
        with self.assertRaises(ContractError):
            self.service.approve(OTHER_UID, request, BROWSER, self.f.vault)
        with self.assertRaises(ContractError):
            self.service.pending(UID, request, "c" * 43)
        from urllib.parse import parse_qsl, urlsplit

        code = dict(parse_qsl(urlsplit(callback).query))["code"]
        status, tokens, _ = self.exchange(code)
        self.assertEqual(status, 200)
        principal = self.service.authenticate(tokens["access_token"])

        def stored(unit):
            parent = unit.get(
                document_path("hub_oauth_connections", self.f.owner, principal.connection_id)
            )
            identity = unit.get(
                document_path(
                    "hub_agent_identities", self.f.owner, self.f.vault, principal.connection_id
                )
            )
            consent = unit.get(
                document_path(
                    "hub_resource_consents", self.f.owner, self.f.vault, principal.connection_id
                )
            )
            return parent, identity, consent

        parent, identity, consent = self.store.transact(stored)
        self.assertEqual(parent["grants"], {})
        self.assertEqual(parent["approvedScopes"], [SCOPE])
        self.assertIsNone(identity)
        self.assertIsNone(consent)

    def test_financial_scope_and_v2_resource_are_rejected(self):
        for change in (
            {"scope": "portfolio:read"},
            {"scope": SCOPE + " tasks:read"},
            {"resource": configuration().resource},
        ):
            with self.assertRaises(OAuthFailure):
                self.service.authorize(self.authorize_params | change, BROWSER)

    def test_optional_locale_hint_does_not_change_native_authority_or_code_exchange(self):
        for locale in ("en-US", "zh-Hans-CN en-US"):
            with self.subTest(locale=locale):
                self.authorize_params["ui_locales"] = locale
                _, _, code = self.authorize()
                status, tokens, _ = self.exchange(code)
                self.assertEqual(status, 200)
                self.assertEqual(tokens["scope"], SCOPE)
                principal = self.service.authenticate(tokens["access_token"])
                self.assertEqual(principal.owner_subject, self.f.owner)
                pending = self.service.transact(
                    lambda unit: unit.get(document_path("hub_oauth_pending", "pool"))
                )
                self.assertTrue(pending["entries"])
                self.assertTrue(
                    all("ui_locales" not in row["params"] for row in pending["entries"].values())
                )

    def test_locale_hint_cannot_carry_unbounded_or_invalid_authorization_fields(self):
        for locale in ("", "en_US", "en\nUS", "en-US " * 30, "a" * 129, 123, None):
            with self.subTest(locale=locale), self.assertRaises(OAuthFailure):
                self.service.authorize(self.authorize_params | {"ui_locales": locale}, BROWSER)
        for change in (
            {"scope": "portfolio:read"},
            {"resource": configuration().resource},
            {"redirect_uri": "https://other.example/callback"},
            {"code_challenge_method": "plain"},
            {"prompt": "none"},
        ):
            with self.subTest(change=change), self.assertRaises(OAuthFailure):
                self.service.authorize(
                    self.authorize_params | {"ui_locales": "en-US"} | change, BROWSER
                )

    def test_native_tokens_are_not_accepted_by_legacy_oauth(self):
        tokens = self.connect()
        legacy = OAuthService(self.store, configuration(), clock=lambda: self.now)
        with self.assertRaises(OAuthFailure):
            legacy.authenticate(tokens["access_token"])
        status, body, _ = legacy.protocol(
            {
                "grant_type": "refresh_token",
                "client_id": CLIENT,
                "refresh_token": tokens["refresh_token"],
                "resource": configuration().resource,
            },
            {},
            "token",
        )
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "invalid_grant")

    def test_refresh_survives_legacy_absolute_deadline_and_extends_only_idle_window(self):
        tokens = self.connect()
        p = self.service.authenticate(tokens["access_token"])
        self.now += 31 * 86400
        status, new, _ = self.refresh(tokens["refresh_token"])
        self.assertEqual(status, 200)
        self.assertNotEqual(new["refresh_token"], tokens["refresh_token"])
        self.assertEqual(
            self.service.authenticate(new["access_token"]).connection_id, p.connection_id
        )
        self.now += 170 * 86400
        status, newer, _ = self.refresh(new["refresh_token"])
        self.assertEqual(status, 200)
        self.assertEqual(
            self.service.authenticate(newer["access_token"]).connection_id, p.connection_id
        )

    def test_refresh_replay_revokes_family_but_not_root_parent(self):
        tokens = self.connect()
        old = self.service.authenticate(tokens["access_token"])
        status, new, _ = self.refresh(tokens["refresh_token"])
        self.assertEqual(status, 200)
        status, body, _ = self.refresh(tokens["refresh_token"])
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "invalid_grant")
        with self.assertRaises(OAuthFailure):
            self.service.authenticate(new["access_token"])
        parent = self.store.transact(
            lambda u: u.get(document_path("hub_oauth_connections", self.f.owner, old.connection_id))
        )
        self.assertEqual(parent["status"], "active")
        repaired = self.connect()
        self.assertEqual(
            self.service.authenticate(repaired["access_token"]).connection_id, old.connection_id
        )

    def test_reopening_approval_does_not_return_a_superseded_used_or_expired_code(self):
        superseded, _, _ = self.authorize()
        current, _, code = self.authorize()
        with self.assertRaisesRegex(ContractError, "not_found"):
            self.service.approve(UID, superseded, BROWSER, self.f.vault)
        status, tokens, _ = self.exchange(code)
        self.assertEqual(status, 200)
        with self.assertRaisesRegex(ContractError, "not_found"):
            self.service.approve(UID, current, BROWSER, self.f.vault)
        self.service.authenticate(tokens["access_token"])

        expired, _, _ = self.authorize()
        self.now += 300
        with self.assertRaisesRegex(ContractError, "not_found"):
            self.service.approve(UID, expired, BROWSER, self.f.vault)

    def test_explicit_native_disconnect_terminally_stops_current_parent(self):
        tokens = self.connect()
        p = self.service.authenticate(tokens["access_token"])
        status, _, _ = self.service.protocol(
            {
                "client_id": CLIENT,
                "token": tokens["refresh_token"],
                "resource": self.service.config.resource,
            },
            {},
            "revoke",
        )
        self.assertEqual(status, 200)
        parent = self.store.transact(
            lambda u: u.get(document_path("hub_oauth_connections", self.f.owner, p.connection_id))
        )
        self.assertEqual(parent["status"], "revoked")
        with self.assertRaises(OAuthFailure):
            self.service.authenticate(tokens["access_token"])

    def test_idle_expiration_requires_account_repair_without_creating_another_parent(self):
        tokens = self.connect()
        p = self.service.authenticate(tokens["access_token"])
        self.now += REFRESH_IDLE_SECONDS + 1
        status, _, _ = self.refresh(tokens["refresh_token"])
        self.assertEqual(status, 400)
        repaired = self.connect()
        self.assertEqual(
            self.service.authenticate(repaired["access_token"]).connection_id, p.connection_id
        )

    def test_old_family_disconnect_cannot_revoke_repaired_current_account(self):
        first = self.connect()
        p = self.service.authenticate(first["access_token"])
        second = self.connect()
        status, _, _ = self.service.protocol(
            {
                "client_id": CLIENT,
                "token": first["refresh_token"],
                "resource": self.service.config.resource,
            },
            {},
            "revoke",
        )
        self.assertEqual(status, 200)
        self.assertEqual(
            self.service.authenticate(second["access_token"]).connection_id, p.connection_id
        )

    def test_bad_pkce_callback_and_client_cannot_exchange_original_code(self):
        _, _, code = self.authorize()
        valid = {
            "grant_type": "authorization_code",
            "client_id": CLIENT,
            "code": code,
            "redirect_uri": CALLBACK,
            "code_verifier": VERIFIER,
            "resource": self.service.config.resource,
        }
        for changes in (
            {"code_verifier": "x" * 43},
            {"redirect_uri": "https://other.example/callback"},
            {"client_id": "unknown_client"},
        ):
            status, _, _ = self.service.protocol(valid | changes, {}, "token")
            self.assertIn(status, (400, 401))
        self.assertEqual(self.exchange(code)[0], 200)

    def test_authorization_code_replay_stops_family_and_never_mints_a_fork(self):
        _, _, code = self.authorize()
        _, tokens, _ = self.exchange(code)
        self.assertEqual(self.exchange(code)[0], 400)
        with self.assertRaises(OAuthFailure):
            self.service.authenticate(tokens["access_token"])

    def test_client_cannot_use_access_as_refresh_or_expand_scope_while_rotating(self):
        tokens = self.connect()
        self.assertEqual(self.refresh(tokens["access_token"])[0], 400)
        with self.assertRaises(OAuthFailure):
            self.service.protocol(
                {
                    "grant_type": "refresh_token",
                    "client_id": CLIENT,
                    "refresh_token": tokens["refresh_token"],
                    "resource": self.service.config.resource,
                    "scope": "portfolio:read",
                },
                {},
                "token",
            )
        self.assertEqual(self.refresh(tokens["refresh_token"])[0], 200)

    def test_confidential_client_requires_registered_basic_secret_for_exchange(self):
        import base64

        value = "synthetic" + "_native_client_value"
        self.service = NativeTransportService(
            self.store, configuration(value), clock=lambda: self.now
        )
        _, _, code = self.authorize()
        self.assertEqual(self.exchange(code)[0], 401)
        form = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": CALLBACK,
            "code_verifier": VERIFIER,
            "resource": self.service.config.resource,
        }
        headers = {
            "Authorization": "Basic " + base64.b64encode((CLIENT + ":" + value).encode()).decode()
        }
        status, tokens, _ = self.service.protocol(form, headers, "token")
        self.assertEqual(status, 200)
        self.assertEqual(self.service.authenticate(tokens["access_token"]).client_id, CLIENT)

    def test_database_callback_cache_contains_no_plain_code_or_callback_and_is_request_bound(self):
        request, callback, code = self.authorize()
        pending = self.store.transact(
            lambda u: u.get(document_path("hub_native_oauth_pending", "pool"))
        )
        from folioview_shared.encrypted.jsonutil import canonical_json

        raw = canonical_json(pending).decode()
        self.assertNotIn(code, raw)
        self.assertNotIn(callback, raw)
        self.assertEqual(self.service.approve(UID, request, BROWSER, self.f.vault), callback)

    def test_native_history_is_separate_from_legacy_connections_and_remains_readable_when_disabled(
        self,
    ):
        from app.native_transport import NativeConnectionOwnerService
        from app.oauth import OwnerConnectionService

        tokens = self.connect()
        principal = self.service.authenticate(tokens["access_token"])
        native = NativeConnectionOwnerService(self.store, clock=lambda: self.now)
        self.assertEqual(OwnerConnectionService(self.store).connections(UID)["items"], [])
        view = native.native_connections(UID)["connections"][0]
        self.assertEqual(view["connectionId"], principal.connection_id)
        self.assertEqual(view["accountState"], "connected")
        with self.assertRaises(ContractError):
            native.native_disconnect(OTHER_UID, principal.connection_id)
        self.assertEqual(
            native.native_disconnect(UID, principal.connection_id)["connection"]["status"],
            "revoked",
        )
        self.assertEqual(
            native.native_disconnect(UID, principal.connection_id)["connection"]["status"],
            "revoked",
        )
        with self.assertRaises(OAuthFailure):
            self.service.authenticate(tokens["access_token"])

    def test_account_repair_preserves_actual_root_identity_and_resource_consent(self):
        from test_persistent_resource_store import Catalogue

        from app.persistent_agents import PersistentAgentService
        from app.resource_consents import ResourceConsentService
        from folioview_shared.encrypted.constants import CONTRACT_VERSION
        from folioview_shared.encrypted.persistent_agents import PERSISTENT_AGENT_PROFILE
        from folioview_shared.encrypted.persistent_content import BINDING_FIELDS
        from folioview_shared.encrypted.resource_consents import RESOURCE_CONSENT_PROFILE

        tokens = self.connect()
        principal = self.service.authenticate(tokens["access_token"])
        connection = principal.connection_id
        self.f.add_key("A1_sig", "agent_sig", "native_agent", connection)
        self.f.add_key("A1_enc", "agent_enc", "native_agent", connection)
        self.f.bundle = self.f.make_bundle(previous=self.f.registry, issued_at=1000)
        self.f.registry = self.f.verify(self.f.bundle, previous=self.f.registry)
        VaultService(self.store, clock=lambda: self.now).update_registry(
            UID,
            self.f.vault,
            {
                "contractVersion": CONTRACT_VERSION,
                "expectedVersion": 1,
                "registryBundle": self.f.bundle,
            },
            "synthetic_native_registry_01",
        )
        agents = PersistentAgentService(self.store, client_ids=[CLIENT], clock=lambda: self.now)
        operation = "synthetic_native_identity_bind_01"
        binding = {
            **self.f.base("persistent_agent_binding"),
            "profile": PERSISTENT_AGENT_PROFILE,
            "rootKeyId": self.f.root_id,
            "connectionId": connection,
            "agentId": "native_agent",
            "clientId": CLIENT,
            "identityEpoch": 1,
            "agentSigningKeyId": self.f.kid("A1_sig"),
            "agentEncryptionKeyId": self.f.kid("A1_enc"),
            "deviceSigningKeyId": self.f.kid("device_sig"),
            "stableOperationId": operation,
            "registrySequence": self.f.registry.registry_sequence,
            "checkpointDigest": self.f.registry.checkpoint_digest,
            "keyEpoch": 1,
            "issuedAt": self.now,
        }
        identity = agents.command(UID, self.f.vault, connection, self.f.sign(binding), operation)[
            "identity"
        ]
        catalogue = Catalogue([self.f.resource])
        catalogue.revision = 1
        consents = ResourceConsentService(self.store, catalogue, clock=lambda: self.now)
        operation = "synthetic_native_consent_approval_01"
        approval = {
            "contractVersion": CONTRACT_VERSION,
            "profile": RESOURCE_CONSENT_PROFILE,
            **{k: identity[k] for k in BINDING_FIELDS},
            "artifactType": "persistent_resource_approval",
            "consentId": "native_consent",
            "purpose": "analysis",
            "authorKeyId": self.f.root_id,
            "stableOperationId": operation,
            "expectedVersion": 0,
            "expectedConsentDigest": None,
            "issuedAt": self.now,
            "registrySequence": self.f.registry.registry_sequence,
            "checkpointDigest": self.f.registry.checkpoint_digest,
            "keyEpoch": 1,
            "resources": [
                {
                    "permissionId": "native_permission",
                    "ref": self.f.resource,
                    "sourceEpoch": 1,
                    "fromRevision": 1,
                    "versionPolicy": "current_and_future",
                    "selectedHistory": [],
                    "expectedPermissionEpoch": 0,
                }
            ],
        }
        policy = consents.command(
            UID, self.f.vault, connection, self.f.sign(approval, "root"), operation
        )["consent"]
        self.refresh(tokens["refresh_token"])
        self.refresh(tokens["refresh_token"])
        repaired = self.connect()
        self.assertEqual(
            self.service.authenticate(repaired["access_token"]).connection_id, connection
        )
        self.assertEqual(agents.state(UID, self.f.vault, connection)["identity"], identity)
        self.assertEqual(consents.state(UID, self.f.vault, connection)["consent"], policy)
