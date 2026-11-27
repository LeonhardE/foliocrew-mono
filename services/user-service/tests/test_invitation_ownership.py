"""Stable invited-owner associations survive email changes and never erase another user."""

import copy
import os
import unittest
from uuid import uuid4

from google.cloud import firestore

from app import account_erasure as erasure
from app.invitation_erasure import InvitationReviewRequired
from app.repair_invitation_binding import original_binding, repair
from app.workspace_invitations import INVITATIONS, MEMBERS, InvitationStore, invitation_id
from folioview_shared.identity import owner_key


@unittest.skipUnless(
    os.getenv("FIRESTORE_EMULATOR_HOST", "").startswith(("localhost:", "127.0.0.1:")),
    "requires a local Firestore emulator",
)
class InvitationOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.project = "demo-invite-" + uuid4().hex[:9]
        self.db = firestore.Client(project=self.project, database="user-data")
        self.addCleanup(self.db.close)
        self.invites = self.db.collection(INVITATIONS)
        self.subject = erasure.Subject("old-uid", "now@gmail.com", "stable-google")
        self.control = erasure.Subject("other-uid", "now@gmail.com", "other-google")
        self.issuer = InvitationStore(self.db)
        self.old = "former@gmail.com"
        self.key = "workspace-invite/" + "a" * 32

    def seed(self, email, delivery):
        ref = self.invites.document(invitation_id(email))
        ref.set(
            {
                "email": email,
                "status": "invited",
                "deliveryKey": self.key,
                "expiresAt": 5000,
                "providerMessageId": delivery,
            }
        )
        return ref

    def bind(self, subject, email):
        self.assertTrue(
            self.issuer.admit(subject.uid, subject.google_subject, email, 1000, bind=True)
        )

    def erase(self, *, apply):
        return erasure.firestore_erasure(
            self.db, self.subject, apply=apply, check_suspension=lambda: None
        )

    def test_changed_address_and_reused_address_only_return_the_original_delivery(self):
        original = self.seed(self.old, "original-delivery")
        reused = self.seed(self.subject.email, "control-delivery")
        self.bind(self.subject, self.old)
        self.bind(self.control, self.subject.email)
        self.assertEqual(erasure.delivery_refs(self.db, self.subject), ["original-delivery"])
        self.assertEqual(self.erase(apply=True), {MEMBERS: 1, INVITATIONS: 1})
        self.assertEqual(self.erase(apply=False), {})
        self.assertFalse(original.get().exists)
        self.assertEqual(reused.get().get("joinedOwner"), owner_key(self.control.uid))
        self.assertEqual(erasure.delivery_refs(self.db, self.control), ["control-delivery"])

    def test_legacy_binding_requires_independent_original_commit(self):
        legacy = self.seed(self.old, "old-id")
        reused = self.seed(self.subject.email, "other-id")
        self.bind(self.control, self.subject.email)
        member = self.db.collection(MEMBERS).document(owner_key(self.subject.uid))
        member_data = {
            "state": "active",
            "googleSubject": self.subject.google_subject,
            "joinedAt": 1000,
        }
        legacy.update({"status": "joined", "updatedAt": 1000})
        member.set(member_data)
        for read in (
            lambda: self.erase(apply=True),
            lambda: erasure.delivery_refs(self.db, self.subject),
        ):
            with self.assertRaises(InvitationReviewRequired):
                read()
        self.assertTrue(legacy.get().exists)
        self.assertTrue(member.get().exists)
        dbpath = f"projects/{self.project}/databases/user-data"
        fields = {
            "email": {"stringValue": self.old},
            "deliveryKey": {"stringValue": self.key},
            "updatedAt": {"integerValue": "1000"},
            "status": {"stringValue": "joined"},
        }
        members = {
            "googleSubject": {"stringValue": self.subject.google_subject},
            "state": {"stringValue": "active"},
            "joinedAt": {"integerValue": "1000"},
        }
        raw = {
            "request": {
                "@type": "type.googleapis.com/google.firestore.v1.CommitRequest",
                "database": dbpath,
                "writes": [
                    {"update": {"name": dbpath + "/documents/" + member.path, "fields": members}},
                    {"update": {"name": dbpath + "/documents/" + legacy.path, "fields": fields}},
                ],
            }
        }
        evidence = original_binding(self.project, "user-data", self.subject, raw)
        for key, value in (
            ("googleSubject", {"stringValue": "different"}),
            ("joinedAt", {"integerValue": "1001"}),
        ):
            bad = copy.deepcopy(raw)
            bad["request"]["writes"][0]["update"]["fields"][key] = value
            with self.assertRaises(InvitationReviewRequired):
                original_binding(self.project, "user-data", self.subject, bad)
        repair(self.db, self.subject, evidence, apply=False)
        self.assertNotIn("joinedOwner", legacy.get().to_dict())
        repair(self.db, self.subject, evidence, apply=True)
        repair(self.db, self.subject, evidence, apply=True)
        self.assertEqual(erasure.delivery_refs(self.db, self.subject), ["old-id"])
        self.assertEqual(self.erase(apply=True), {MEMBERS: 1, INVITATIONS: 1})
        self.assertTrue(reused.get().exists)
        self.assertEqual(erasure.delivery_refs(self.db, self.control), ["other-id"])

    def test_orphaned_unknown_joined_old_email_blocks_without_revealing_mail_refs(self):
        legacy = self.seed(self.old, "private-delivery")
        legacy.update({"status": "joined", "updatedAt": 1000})
        with self.assertRaises(InvitationReviewRequired):
            erasure.delivery_refs(self.db, self.subject)
        with self.assertRaises(InvitationReviewRequired):
            self.erase(apply=True)
        self.assertTrue(legacy.get().exists)


class AuditLookupTests(unittest.TestCase):
    def test_only_a_successful_entry_from_the_expected_runtime_can_bind_a_legacy_join(self):
        from unittest.mock import MagicMock, patch

        from app.repair_invitation_binding import audit_commit

        project = "testing-project"
        log = "projects/testing-project/logs/cloudaudit.googleapis.com%2Fdata_access"
        writer = "fa-user-runtime@testing-project.iam.gserviceaccount.com"
        info = {
            "@type": "type.googleapis.com/google.cloud.audit.AuditLog",
            "methodName": "google.firestore.v1.Firestore.Commit",
            "serviceName": "firestore.googleapis.com",
            "authenticationInfo": {"principalEmail": writer},
        }
        record = {"logName": log, "insertId": "entry-one", "protoPayload": info}
        session = MagicMock()
        response = session.return_value.__enter__.return_value.post.return_value
        with (
            patch(
                "app.repair_invitation_binding.google.auth.default", return_value=(object(), None)
            ),
            patch("app.repair_invitation_binding.AuthorizedSession", session),
        ):
            response.json.return_value = {"entries": [record]}
            self.assertEqual(audit_commit(project, "entry-one", writer), info)
            for body in (
                {"entries": []},
                {"entries": [record], "nextPageToken": "additional-page"},
                {"entries": [{**record, "logName": "projects/other/logs/custom"}]},
                {"entries": [{**record, "insertId": "different"}]},
                {"entries": [{**record, "protoPayload": {**info, "status": {"code": 7}}}]},
                {"entries": [{**record, "protoPayload": {**info, "authenticationInfo": {}}}]},
            ):
                response.json.return_value = body
                with self.assertRaises(InvitationReviewRequired):
                    audit_commit(project, "entry-one", writer)
