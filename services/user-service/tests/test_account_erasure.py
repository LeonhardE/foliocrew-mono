"""Physical reads, second-owner isolation, interrupted writes and old-snapshot recovery."""

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from fastapi import HTTPException
from google.cloud import firestore
from test_private_recovery import UID, registry_fixture
from test_watchlist import item

from app import account_erasure as erasure
from app.private_resources.display_name_cleanup import NAMES, OPERATIONS, erase_retired_names
from app.private_resources.recovery import RecoveryHeads
from app.private_resources.registry_pages import RegistryHistory
from app.resources import FirestoreUserResourceStore, SQLiteUserResourceStore
from app.watchlist import SQLiteWatchlistStore
from app.workspace_invitations import INVITATIONS, InvitationStore, finish_delivery, invitation_id
from folioview_shared.encrypted.errors import ContractError
from folioview_shared.encrypted.jsonutil import canonical_json
from folioview_shared.encrypted.private_resources import PrivateRegistryCursor
from folioview_shared.identity import owner_key


class ErasureTests(unittest.TestCase):
    def test_application_reads_raw_records_and_restore(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "user.sqlite"
            image = Path(directory) / "offline-restore.sqlite"
            store = SQLiteUserResourceStore(str(path))
            target = erasure.Subject(UID, "target@example.test", "google-target")
            control = erasure.Subject("control", "control@example.test", "google-control")
            lists = SQLiteWatchlistStore(str(path))
            for subject in (target, control):
                lists.change(subject.uid, "AAPL", item())
                store.initialize(subject.uid, "watchlist", "fixture")
            _, root, _, registry, bundle, _ = registry_fixture()
            RegistryHistory(RecoveryHeads(store)).stage(
                bundle, root_jwk=root, cursor=PrivateRegistryCursor(registry, 1)
            )
            # Ordinary list-item deletion must preserve the active list's identity and revision.
            lists.change(UID, "AAPL", None)
            self.assertEqual(lists.get(UID), [])
            self.assertEqual(store.read(UID, ("watchlist",))["watchlist"]["state"], "empty")
            shutil.copyfile(path, image)
            inventory = erasure.sqlite_erasure(path, target)
            self.assertEqual(sum(inventory.values()), 4)
            before = erasure.sqlite_erasure(path, control)
            with closing(sqlite3.connect(path)) as db, db:
                db.execute(
                    "CREATE TRIGGER abort_erasure BEFORE DELETE ON user_resource_versions "
                    "BEGIN SELECT RAISE(ABORT, 'simulated interruption'); END"
                )
            with self.assertRaises(sqlite3.IntegrityError):
                erasure.sqlite_erasure(path, target, apply=True)
            self.assertEqual(erasure.sqlite_erasure(path, target), inventory)
            with closing(sqlite3.connect(path)) as db, db:
                db.execute("DROP TRIGGER abort_erasure")
            for target_db in (path, image):
                self.assertEqual(erasure.sqlite_erasure(target_db, target, apply=True), inventory)
                self.assertEqual(erasure.sqlite_erasure(target_db, target, apply=True), {})
                self.assertEqual(erasure.sqlite_erasure(target_db, control), before)
                self.assertEqual(SQLiteWatchlistStore(str(target_db)).get(control.uid), [item()])

    def test_apply_requires_a_verified_suspended_google_identity(self):
        provider = SimpleNamespace(provider_id="google.com", uid="google-target", email="x@a.test")
        account = SimpleNamespace(
            uid="abc",
            email="x@a.test",
            email_verified=True,
            provider_data=[provider],
            disabled=False,
        )
        with self.assertRaises(erasure.ErasureIncomplete):
            erasure.verified_subject(account, account.email, apply=True)
        account.disabled = True
        expected = erasure.Subject("abc", account.email, provider.uid)
        self.assertEqual(erasure.verified_subject(account, account.email, apply=True), expected)
        with self.assertRaises(erasure.ErasureIncomplete):
            erasure.verified_subject(account, "other@a.test", apply=True)
        account.email_verified = False
        with self.assertRaises(erasure.ErasureIncomplete):
            erasure.verified_subject(account, account.email, apply=False)

    def test_invalid_opaque_owner_binding_fails_before_deletion(self):
        subject = erasure.Subject(UID, "target@example.test", "google-target")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "db"
            lists = SQLiteWatchlistStore(str(path))
            lists.change(UID, "AAPL", item())
            with closing(sqlite3.connect(path)) as db, db:
                db.execute(f"CREATE TABLE {erasure.BASELINES} (key TEXT PRIMARY KEY, body BLOB)")
                db.execute(
                    f"INSERT INTO {erasure.BASELINES} VALUES ('invalid',?)",
                    (canonical_json({"ownerSubject": owner_key(UID), "vaultId": "vault"}),),
                )
            with self.assertRaises(erasure.ErasureIncomplete):
                erasure.sqlite_erasure(path, subject, apply=True)
            self.assertEqual(lists.get(UID), [item()])


@unittest.skipUnless(
    os.getenv("USER_ERASURE_TEST_EMULATOR") == "1"
    and os.getenv("FIRESTORE_EMULATOR_HOST", "").split(":")[0] in ("127.0.0.1", "localhost"),
    "Requires a loopback Firestore emulator",
)
class FirestoreErasureTests(unittest.TestCase):
    def setUp(self):
        project = "demo-erase-" + uuid4().hex[:12]
        self.client = firestore.Client(project=project, database="user-data")
        self.addCleanup(self.client.close)

    def test_inventory_interruption_resume_zero_readback_and_other_account(self):
        target = erasure.Subject(UID, "target@gmail.com", "google-target")
        control = erasure.Subject("control", "control@gmail.com", "google-control")
        counts = {}
        for subject in (target, control):
            rows = {}
            for table, key in erasure.fixed_keys(subject):
                data = {"fixture": "private"}
                if table == erasure.MEMBERS:
                    data = {"googleSubject": subject.google_subject}
                if table == erasure.INVITATIONS:
                    data = {"email": subject.email}
                rows[table, key] = data
            for table, field in erasure.INDEXED.items():
                value = {"ownerSubject": owner_key(subject.uid)}
                rows[table, subject.uid] = {"state": value} if field.startswith("state.") else value
            for n in range(105):
                rows[erasure.REGISTRY_MUTATIONS, f"{subject.uid}-{n}"] = {
                    "ownerSubject": owner_key(subject.uid)
                }
            body = canonical_json({"ownerSubject": owner_key(subject.uid), "vaultId": "vault"})
            digest = erasure.hashlib.sha256(body).hexdigest()
            key = erasure.LegacyVaultBaselines._key(owner_key(subject.uid), "vault", digest)
            rows[erasure.BASELINES, key] = {"body": body}
            scope = {
                "ownerSubject": owner_key(subject.uid),
                "vaultId": "vault",
                "rootKeyId": "A" * 43,
                "registryEpoch": 1,
            }
            rows[erasure.RETENTION, erasure.hashlib.sha256(canonical_json(scope)).hexdigest()] = {
                "body": canonical_json({"watermark": {**scope, "generation": 1}})
            }
            batch = self.client.batch()
            for (table, key), data in rows.items():
                batch.set(self.client.collection(table).document(key), data)
            batch.commit()
            counts[subject.uid] = len(rows)

        def run(subject, apply=False, check=lambda: None):
            return erasure.firestore_erasure(
                self.client, subject, apply=apply, check_suspension=check
            )

        self.assertEqual(sum(run(target).values()), counts[target.uid])
        checks = iter([True, False])

        def interrupt():
            if not next(checks):
                raise erasure.ErasureIncomplete()

        with self.assertRaises(erasure.ErasureIncomplete):
            run(target, True, interrupt)
        self.assertEqual(sum(run(target).values()), counts[target.uid] - 100)
        run(target, True)
        self.assertEqual(run(target), {})
        self.assertEqual(sum(run(control).values()), counts[control.uid])

    def test_all_frozen_archive_envelopes_removed_by_scope_and_cannot_be_restaged(self):

        target = owner_key("archived")
        other = owner_key("control")
        scope = {"ownerSubject": target, "vaultId": "vault", "rootKeyId": "root"}
        store = FirestoreUserResourceStore(self.client.project, "user-data")
        baseline = erasure.LegacyVaultBaselines(store)

        def write(row):
            raw = canonical_json(row)
            digest = hashlib.sha256(raw).hexdigest()
            ref = self.client.collection(erasure.BASELINES).document(
                baseline._key(row["ownerSubject"], row["vaultId"], digest)
            )
            ref.set({"body": raw})
            return ref, digest, raw

        matching = [write({**scope, "archive": {"ciphertext": sample}}) for sample in ("v1", "v2")]
        controls = [
            write({**scope, "ownerSubject": other, "archive": {"ciphertext": "control"}}),
            write({**scope, "vaultId": "second", "archive": {"ciphertext": "other vault"}}),
            write({**scope, "rootKeyId": "second", "archive": {"ciphertext": "other root"}}),
            write({**scope, "originalOperations": {}}),
        ]
        self.client.collection(erasure.ARCHIVE_RECORDS).document(target).set({"record": b"receipt"})
        for apply in (False, True):
            self.assertEqual(baseline.erase_archives(target, "vault", "root", apply=apply), 2)
        self.assertEqual(baseline.erase_archives(target, "vault", "root"), 0)
        self.assertTrue(all(not ref.get().exists for ref, _, _ in matching))
        self.assertTrue(all(ref.get().exists for ref, _, _ in controls))
        with self.assertRaisesRegex(ContractError, "version_conflict"):
            baseline._stage_bytes(target, "vault", matching[0][2], matching[0][1], archive=True)
        self.assertFalse(matching[0][0].get().exists)

    def test_delivery_lookup_returns_only_verified_address_receipt_without_mutation(self):
        target = erasure.Subject("target", "a@gmail.com", "sub-a")
        control = erasure.Subject("control", "b@gmail.com", "sub-b")
        collection = self.client.collection(INVITATIONS)
        ref = collection.document(invitation_id(target.email))
        self.assertEqual(erasure.delivery_refs(self.client, target), [])
        collection.document(invitation_id(control.email)).set(
            {"email": control.email, "providerMessageId": "control-id"}
        )
        ref.set({"email": target.email, "providerMessageId": "delivery-id"})
        self.assertEqual(erasure.delivery_refs(self.client, target), ["delivery-id"])
        ref.update({"providerMessageId": None})
        self.assertEqual(erasure.delivery_refs(self.client, target), [])
        ref.update({"providerMessageId": "unexpected\nidentifier"})
        with self.assertRaises(erasure.ErasureIncomplete):
            erasure.delivery_refs(self.client, target)
        ref.update({"email": control.email, "providerMessageId": "control-id"})
        with self.assertRaises(erasure.ErasureIncomplete):
            erasure.delivery_refs(self.client, target)
        self.assertEqual(erasure.delivery_refs(self.client, control), ["control-id"])

    def test_read_only_restore_cli_uses_archived_identity_in_absence_of_firebase(self):
        subject = erasure.Subject("former-uid", "former@example.test", "former-google")
        ref = self.client.collection(erasure.MEMBERS).document(owner_key(subject.uid))
        ref.set({"googleSubject": subject.google_subject})
        cmd = [
            sys.executable,
            "-m",
            "app.account_erasure",
            "--project",
            self.client.project,
            "--database",
            "user-data",
            "--restore-inventory",
        ]
        record = json.dumps(
            {"uid": subject.uid, "email": subject.email, "googleSubject": subject.google_subject}
        )
        result = subprocess.run(cmd, input=record, text=True, capture_output=True, check=True)
        self.assertEqual(
            json.loads(result.stdout),
            {"mode": "restore-inventory", "database": "user-data", "matched": {erasure.MEMBERS: 1}},
        )
        denied = subprocess.run([*cmd, "--apply"], input=record, text=True, capture_output=True)
        self.assertNotEqual(denied.returncode, 0)
        self.assertTrue(ref.get().exists)

    def test_delete_closed_invite_and_stale_delivery(self):
        store = InvitationStore(self.client)
        key = invitation_id("target@gmail.com")
        ref = self.client.collection(INVITATIONS).document(key)
        revision = "1" * 32
        row = {
            "email": "target@gmail.com",
            "status": "revoked",
            "deliveryKey": f"workspace-invite/{revision}",
            "expiresAt": 30,
            "updatedAt": 15,
            "leaseUntil": 15,
            "deliveryStartedAt": 10,
        }
        ref.set(row)
        with self.assertRaises(HTTPException):
            store.delete_closed(key, "2" * 32, 20)
        ref.update({"status": "invited"})
        with self.assertRaises(HTTPException):
            store.delete_closed(key, revision, 20)
        store.delete_closed(key, revision, 31)
        self.assertFalse(ref.get().exists)
        store.delete_closed(key, revision, 31)
        with self.assertRaises(HTTPException):
            finish_delivery(None, revision, "late-completion", 32)
        self.assertFalse(ref.get().exists)

    def test_retired_alias_and_all_receipts_removed_only_in_exact_incarnation(self):
        store = FirestoreUserResourceStore.__new__(FirestoreUserResourceStore)
        store.client = self.client
        ref = {"resourceId": "sourceA", "incarnation": "incA"}
        for table in (NAMES, OPERATIONS):
            for key, owner, inc in (
                ("target", "owner-A", "incA"),
                ("foreign", "owner-B", "incA"),
                ("later", "owner-A", "incB"),
            ):
                self.client.collection(table).document(key).set(
                    {"state": {"ownerSubject": owner, "ref": {**ref, "incarnation": inc}}}
                )
        erase_retired_names(store, "owner-A", ref)
        erase_retired_names(store, "owner-A", ref)
        for table in (NAMES, OPERATIONS):
            self.assertEqual(
                {row.id for row in self.client.collection(table).stream()}, {"foreign", "later"}
            )
