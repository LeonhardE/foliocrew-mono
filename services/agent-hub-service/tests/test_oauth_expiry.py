"""Exercise background expiry against the real legacy and native OAuth implementations."""

import io
import json
import os
import secrets
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import test_native_transport as native
import test_oauth as legacy

from app.oauth_config import digest
from app.oauth_expiry import PAGE, process_oauth_expiry
from app.store import FirestoreHubStore, document_path


class OAuthExpiryTests(unittest.TestCase):
    def setup_flow(self, fixture):
        origin = fixture()
        origin.setUp()
        self.addCleanup(origin.doCleanups)
        return origin

    def read_credential(self, origin, table, plaintext):
        path = document_path(table, digest(plaintext))
        return origin.store.transact(lambda unit: unit.get(path))

    def collect(self, origin, apply=True):
        result = process_oauth_expiry(origin.store, apply=apply, clock=lambda: origin.now)
        self.assertEqual(result["reviewRequired"], 0)
        return result

    def test_one_scheduled_job_erases_due_task_report_and_spent_code_but_preserves_another_account(
        self,
    ):
        import test_task_center_lifecycle as lifecycle
        from fixtures import BOOT, OTHER_UID, UID

        from app import task_retention_worker
        from app.native_transport import NativeTransportService
        from app.tasks import TaskService
        from app.vaults import VaultService
        from folioview_shared.encrypted.errors import ContractError

        disposed = self.setup_flow(lifecycle.TaskLifecycleTests)
        report = disposed.fx.submit(disposed.fx.begin())
        disposed.lifecycle("trash")
        cutoff = disposed.fx.definition["purgeAfter"]
        now = disposed.fx.fx.now
        store = disposed.fx.store
        other = legacy.OAuthFixture(OTHER_UID)
        VaultService(store, clock=lambda: now).bootstrap(OTHER_UID, other.bootstrap(), BOOT)
        tasks = TaskService(store, clock=lambda: now)
        keep_id = "unrelated_active_task"
        tasks.create(
            OTHER_UID,
            other.task_body(task=keep_id),
            "synthetic_oauth_task_create_1",
            other.kid("device_sig"),
        )

        kept_task = tasks.get(OTHER_UID, keep_id)
        self.assertTrue(kept_task)
        flow = native.NativeTransportTests()
        flow.f, flow.store = other, store
        flow.service = NativeTransportService(store, native.configuration(), clock=lambda: now)
        flow.authorize_params = native.authorization_params(
            scope=native.SCOPE, resource=flow.service.config.resource
        )
        _, _, expired = flow.authorize(OTHER_UID)
        _, _, approved = flow.authorize(OTHER_UID)
        status, tokens, _ = flow.exchange(approved)
        self.assertEqual(status, 200)
        now = cutoff
        output = io.StringIO()
        with (
            patch.object(task_retention_worker, "get_store", return_value=store),
            patch("sys.argv", ["retention", "--apply"]),
            redirect_stdout(output),
        ):
            self.assertEqual(task_retention_worker.main(clock=lambda: now), 0)
        counts = json.loads(output.getvalue())
        self.assertEqual(counts["completed"], 1)
        self.assertGreaterEqual(counts["oauth"]["expiredRecords"], 1)
        self.assertNotIn(expired, output.getvalue())
        self.assertNotIn(legacy.TASK, output.getvalue())
        self.assertIsNone(self.read_credential(flow, "hub_native_oauth_codes", expired))
        self.assertTrue(disposed.owner.maintenance(UID, disposed.f.vault, legacy.TASK)["complete"])
        with self.assertRaises(ContractError):
            disposed.fx.history.owner_get(UID, disposed.f.vault, report["resultId"])
        self.assertEqual(tasks.get(OTHER_UID, keep_id), kept_task)
        self.assertEqual(flow.refresh(tokens["refresh_token"])[0], 200)

    def test_legacy_spent_code_preserves_family_replay_until_final_expiration(self):
        origin = self.setup_flow(legacy.OAuthTests)
        tokens, _, code = origin.consent()
        family = self.read_credential(origin, "hub_oauth_refresh", tokens["refresh_token"])
        deadline = family["expiresAt"]
        origin.now += 601
        preview = self.collect(origin, apply=False)
        self.assertGreater(preview["replayRecords"], 0)
        self.assertIn("redirect_uri", self.read_credential(origin, "hub_oauth_codes", code))
        self.assertEqual(self.collect(origin), preview)
        self.assertIsNone(self.read_credential(origin, "hub_oauth_access", tokens["access_token"]))
        marker = self.read_credential(origin, "hub_oauth_codes", code)
        self.assertEqual(set(marker), {"context", "client_id", "expiresAt", "resource", "used"})
        self.assertEqual(set(marker["context"]), {"familyId", "ownerSubject"})
        self.assertEqual(marker["expiresAt"], deadline)
        self.assertEqual(origin.service.protocol(legacy.exchange_form(code), {}, "token")[0], 400)
        family_path = document_path("hub_oauth_families", family["familyId"])
        self.assertTrue(origin.store.transact(lambda unit: unit.get(family_path))["revoked"])
        origin.now = deadline
        self.assertGreaterEqual(self.collect(origin)["expiredRecords"], 3)
        self.assertIsNone(self.read_credential(origin, "hub_oauth_codes", code))
        self.assertIsNone(origin.store.transact(lambda unit: unit.get(family_path)))
        self.assertEqual(origin.service.protocol(legacy.exchange_form(code), {}, "token")[0], 400)
        self.assertTrue(origin.service.connections(legacy.UID)["items"])
        self.assertFalse(any(self.collect(origin).values()))

    def test_native_extended_family_preserves_refresh_replay_after_first_deadline(self):
        origin = self.setup_flow(native.NativeTransportTests)
        old = origin.connect()
        original = self.read_credential(origin, "hub_native_oauth_refresh", old["refresh_token"])
        origin.now = original["expiresAt"] - 1
        status, current, _ = origin.refresh(old["refresh_token"])
        self.assertEqual(status, 200)
        origin.now += 2
        result = self.collect(origin)
        self.assertGreaterEqual(result["replayRecords"], 3)
        marker = self.read_credential(origin, "hub_native_oauth_refresh", old["refresh_token"])
        self.assertTrue(marker["used"] and marker["revoked"])
        self.assertNotIn("connectionId", marker)
        self.assertGreater(marker["expiresAt"], origin.now)
        self.assertEqual(origin.refresh(old["refresh_token"])[0], 400)
        self.assertEqual(origin.refresh(current["refresh_token"])[0], 400)
        origin.now = marker["expiresAt"]
        self.collect(origin)
        self.assertIsNotNone(
            self.read_credential(origin, "hub_native_oauth_refresh", old["refresh_token"])
        )
        # An expired transport can still disconnect its original enrolled parent.
        call = {
            "client_id": native.CLIENT,
            "token": old["refresh_token"],
            "resource": origin.service.config.resource,
        }
        self.assertEqual(origin.service.protocol(call, {}, "revoke")[0], 200)
        self.collect(origin)
        self.assertIsNone(
            self.read_credential(origin, "hub_native_oauth_refresh", old["refresh_token"])
        )

    def test_new_authorization_releases_previous_expired_revocation_markers(self):
        origin = self.setup_flow(native.NativeTransportTests)
        tokens = origin.connect()
        row = self.read_credential(origin, "hub_native_oauth_refresh", tokens["refresh_token"])
        origin.now = row["expiresAt"]
        self.collect(origin)
        self.assertFalse(any(self.collect(origin).values()))
        used_family = document_path("hub_native_oauth_families", row["familyId"])
        family = origin.store.transact(lambda unit: unit.get(used_family))
        self.assertTrue(family["revoked"])
        self.assertNotIn("currentRefreshHash", family)
        self.assertNotIn("grantRefs", family)
        newer = origin.connect()
        self.collect(origin)
        self.assertIsNone(origin.store.transact(lambda unit: unit.get(used_family)))
        self.assertIsNone(
            self.read_credential(origin, "hub_native_oauth_access", tokens["access_token"])
        )
        self.assertIsNone(
            self.read_credential(origin, "hub_native_oauth_refresh", tokens["refresh_token"])
        )
        call = {
            "client_id": native.CLIENT,
            "token": tokens["access_token"],
            "resource": origin.service.config.resource,
        }
        self.assertEqual(origin.service.protocol(call, {}, "revoke")[0], 200)
        self.assertEqual(origin.refresh(newer["refresh_token"])[0], 200)

    def test_unused_code_expires_without_interrupting_a_newer_exchange(self):
        origin = self.setup_flow(native.NativeTransportTests)
        _, _, expired = origin.authorize()
        first = self.read_credential(origin, "hub_native_oauth_codes", expired)
        origin.now = first["expiresAt"] - 1
        _, _, latest = origin.authorize()
        origin.now += 1
        self.collect(origin)
        self.assertIsNone(self.read_credential(origin, "hub_native_oauth_codes", expired))
        self.assertEqual(origin.exchange(expired)[0], 400)
        self.assertEqual(origin.exchange(latest)[0], 200)

    def test_expired_native_access_preserves_only_explicit_revocation(self):
        origin = self.setup_flow(native.NativeTransportTests)
        tokens = origin.connect()
        principal = origin.service.authenticate(tokens["access_token"])
        origin.now += 601
        self.collect(origin)
        access = self.read_credential(origin, "hub_native_oauth_access", tokens["access_token"])
        self.assertTrue(access["revoked"])
        self.assertNotIn("grantRefs", access)
        with self.assertRaises(native.OAuthFailure):
            origin.service.authenticate(tokens["access_token"])
        status, _, _ = origin.service.protocol(
            {
                "client_id": native.CLIENT,
                "token": tokens["access_token"],
                "resource": origin.service.config.resource,
            },
            {},
            "revoke",
        )
        self.assertEqual(status, 200)
        conn = document_path("hub_oauth_connections", origin.f.owner, principal.connection_id)
        self.assertEqual(origin.store.transact(lambda unit: unit.get(conn))["status"], "revoked")

    def test_pool_preserves_anonymous_live_requests_and_rechecks_concurrent_renewal(self):
        origin = self.setup_flow(native.NativeTransportTests)
        pool = document_path("hub_native_oauth_pending", "pool")
        entries = {"anonymous": {"expiresAt": 2000}, "past": {"expiresAt": 999}}
        origin.store.transact(
            lambda unit: unit.put(pool, {"count": 2, "window": 1, "entries": entries})
        )
        access = document_path("hub_oauth_access", "synthetic_expired_key")
        origin.store.transact(lambda unit: unit.put(access, {"expiresAt": 999}))
        original = origin.store.transact
        from app import oauth_expiry

        listing = oauth_expiry._pages

        def page(store, table, now, **options):
            for paths in listing(store, table, now, **options):
                if access in paths:
                    original(lambda unit: unit.put(access, {"expiresAt": 3000}))
                yield paths

        with patch.object(oauth_expiry, "_pages", page):
            self.assertEqual(self.collect(origin)["expiredEntries"], 1)
        self.assertEqual(original(lambda unit: unit.get(access)), {"expiresAt": 3000})
        self.assertEqual(
            original(lambda unit: unit.get(pool)),
            {"count": 2, "window": 1, "entries": {"anonymous": {"expiresAt": 2000}}},
        )

    def test_conflicting_family_owner_requires_review_without_modifying_either_side(self):
        origin = self.setup_flow(native.NativeTransportTests)
        _, _, code = origin.authorize()
        _, tokens, _ = origin.exchange(code)
        path = document_path("hub_native_oauth_codes", digest(code))
        record = origin.store.transact(lambda unit: unit.get(path))
        original_family = document_path("hub_native_oauth_families", record["context"]["familyId"])
        family = origin.store.transact(lambda unit: unit.get(original_family))
        origin.store.transact(
            lambda unit: unit.put(original_family, {**family, "ownerSubject": "b" * 64})
        )
        origin.now += 601
        result = process_oauth_expiry(origin.store, apply=True, clock=lambda: origin.now)
        self.assertGreaterEqual(result["reviewRequired"], 1)
        self.assertEqual(origin.store.transact(lambda unit: unit.get(path)), record)
        self.assertIn(
            "grantRefs",
            self.read_credential(origin, "hub_native_oauth_access", tokens["access_token"]),
        )


@unittest.skipUnless(os.getenv("HUB_OAUTH_EXPIRY_TEST_EMULATOR") == "1", "loopback Firestore only")
class FirestoreOAuthExpiryTests(unittest.TestCase):
    def test_cursor_deletes_two_pages_and_preserves_live_credential(self):
        from google.auth.credentials import AnonymousCredentials
        from google.cloud import firestore

        self.assertRegex(os.environ["FIRESTORE_EMULATOR_HOST"], r"^127\.0\.0\.1:\d+$")
        project = "demo-oauth-gc-" + secrets.token_hex(4)
        client = firestore.Client(
            project=project, database="agent-hub", credentials=AnonymousCredentials()
        )
        self.addCleanup(client.close)
        store = FirestoreHubStore(project, "agent-hub", client=client)
        table = "hub_oauth_access"
        batch = client.batch()
        for index in range(PAGE + 2):
            path = document_path(table, f"expired_{index}")
            batch.set(client.document(path), {"expiresAt": 3})
        live = client.document(document_path(table, "retained"))
        batch.set(live, {"expiresAt": 55})
        batch.commit()
        counts = process_oauth_expiry(store, apply=True, clock=lambda: 3)
        self.assertEqual(
            counts,
            {
                "expiredEntries": 0,
                "reviewRequired": 0,
                "expiredRecords": PAGE + 2,
                "replayRecords": 0,
            },
        )
        self.assertEqual([r.reference.path for r in client.collection(table).stream()], [live.path])
