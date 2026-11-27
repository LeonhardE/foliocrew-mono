"""Workspace admission and delivery tests without real accounts or email."""

import json
import os
import unittest
from copy import deepcopy
from threading import Lock
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from app import workspace_invitations as invites
from app import workspace_invite_delivery as delivery
from app.main import app
from app.workspace_invite_delivery import DeliveryUnconfirmed
from folioview_shared import auth
from folioview_shared.encrypted import CONTRACT_VERSION

API = "/api/v1/workspace-invitations"
INTERNAL = "/internal/v2/workspace-invitations"
ADMIN = "test-admin-uid"
EMAIL = "example.invitee@gmail.com"
BEARER = {"Authorization": "Bearer test-id-token"}
NOW = 1_800_000_000


class WorkspaceInviteDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(
            patch.dict(
                os.environ,
                {
                    "FIREBASE_PROJECT_ID": "fixture-invite-staging",
                    "FOLIOCREW_INVITATION_MAIL_KEY": "mock-provider-credential",
                },
                clear=True,
            )
        )
        self.transport = self.enterContext(patch.object(delivery.http.client, "HTTPSConnection"))
        result = self.transport.return_value.getresponse.return_value
        result.status = 200
        result.read.return_value = b'{"id":"provider-message"}'

    def message(self):
        self.assertEqual(delivery.send_invitation(EMAIL, "fixture-delivery"), "provider-message")
        self.transport.assert_called_once_with("api.resend.com", timeout=8)
        request = self.transport.return_value.request.call_args.args
        self.assertEqual(request[:2], ("POST", "/emails"))
        self.assertEqual(request[3]["Idempotency-Key"], "fixture-delivery")
        return json.loads(request[2])

    def test_production_invitation_uses_the_default_workbench(self):
        message = self.message()
        self.assertEqual(message["to"], [EMAIL])
        self.assertEqual(message["subject"], "You’re invited to Foliocrew")
        self.assertIn("https://hub.foliocrew.app/", message["text"])

    def test_staging_invitation_uses_its_own_firebase_host(self):
        os.environ["FOLIOCREW_INVITATION_STAGING_ORIGIN"] = "https://fixture-invite-staging.web.app"
        message = self.message()
        self.assertTrue(message["subject"].startswith("[Staging] "))
        self.assertIn("https://fixture-invite-staging.web.app/", message["text"])
        self.assertNotIn("hub.foliocrew.app", message["text"])

    def test_staging_invitation_rejects_another_origin_before_contacting_provider(self):
        for origin in (
            "",
            "https://another-project.web.app",
            "http://fixture-invite-staging.web.app",
            "https://fixture-invite-staging.web.app/redirect",
        ):
            with self.subTest(origin=origin):
                os.environ["FOLIOCREW_INVITATION_STAGING_ORIGIN"] = origin
                with self.assertRaises(DeliveryUnconfirmed):
                    delivery.send_invitation(EMAIL, "fixture-delivery")
        self.transport.assert_not_called()


class MemoryStore:
    def __init__(self):
        self.rows = {}
        self.members = {}
        self.lock = Lock()

    def change(self, key, transform):
        with self.lock:
            row, result = transform(deepcopy(self.rows.get(key)))
            if row is not None:
                self.rows[key] = deepcopy(row)
        return result

    def list(self, after):
        return [self.rows[key] for key in sorted(self.rows) if after is None or key > after]

    def admit(self, uid, subject, email, now, *, bind):
        with self.lock:
            member = self.members.get(uid)
            invite = self.rows.get(invites.invitation_id(email))
            allowed = invites.admission_allowed(member, invite, subject, now)
            if allowed and bind and member is None:
                self.members[uid] = {"googleSubject": subject, "state": "active"}
                invite.update(status="joined", updatedAt=now)
            return allowed

    def has_membership(self, uid):
        return self.members.get(uid, {}).get("state") == "active"


class WorkspaceInvitationTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(
            patch.dict(
                os.environ,
                {
                    "FOLIOCREW_INVITATIONS_ENABLED": "1",
                    "FOLIOCREW_INVITATION_ADMIN_UID": ADMIN,
                    "FOLIOCREW_INVITATION_MAIL_KEY": "mock-provider-credential",
                    "FIREBASE_PROJECT_ID": "test-financial-analysis",
                },
                clear=True,
            )
        )
        self.store = MemoryStore()
        self.store_lookup = Mock(return_value=self.store)
        self.enterContext(
            patch.dict(
                app.dependency_overrides,
                {invites.get_invitation_store: lambda: self.store_lookup()},
            )
        )
        self.enterContext(patch.object(invites, "get_invitation_store", self.store_lookup))
        self.enterContext(
            patch.object(
                auth.firebase_admin,
                "get_app",
                return_value=SimpleNamespace(project_id="test-financial-analysis"),
            )
        )
        self.claims = self.enterContext(
            patch.object(
                auth.auth,
                "verify_id_token",
                return_value={"uid": ADMIN, "firebase": {"sign_in_provider": "google.com"}},
            )
        )
        self.clock = self.enterContext(
            patch.object(invites, "time", SimpleNamespace(time=Mock(return_value=NOW)))
        )
        self.send = self.enterContext(
            patch.object(invites, "send_invitation", return_value="provider-message")
        )
        self.client = self.enterContext(TestClient(app))

    def create(self, email=EMAIL, **extra):
        return self.client.post(API, headers=BEARER, json={"email": email, **extra})

    def action(self, row, action):
        return self.client.post(f"{API}/{row['id']}/{row['revision']}/{action}", headers=BEARER)

    def test_settings_capability_and_admin_actions_use_verified_uid(self):
        forbidden = self.client.get(API, headers={"X-User-Id": ADMIN})
        self.assertEqual(forbidden.status_code, 401)
        self.assertEqual(forbidden.headers["cache-control"], "no-store")
        self.claims.return_value["uid"] = "not-the-admin"
        self.assertEqual(
            self.client.get(f"{API}/capability", headers=BEARER).json(),
            {"canManageInvitations": False},
        )
        self.assertEqual(self.client.get(API, headers=BEARER).status_code, 403)
        self.assertEqual(self.create().status_code, 403)
        self.assertEqual(
            self.client.delete(f"{API}/{'a' * 64}/{'a' * 32}", headers=BEARER).status_code, 403
        )
        self.store_lookup.assert_not_called()
        self.send.assert_not_called()
        self.claims.return_value["uid"] = ADMIN
        self.assertEqual(
            self.client.get(f"{API}/capability", headers=BEARER).json(),
            {"canManageInvitations": True},
        )
        os.environ.pop("FOLIOCREW_INVITATION_ADMIN_UID")
        self.assertEqual(self.create().status_code, 403)
        self.assertEqual(
            self.client.delete(f"{API}/{'a' * 64}/{'a' * 32}", headers=BEARER).status_code, 403
        )

    def test_exact_gmail_invitation_is_idempotent_and_private(self):
        response = self.create(" Example.Invitee@Gmail.Com ")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers["cache-control"], "no-store")
        item = response.json()
        self.assertEqual(item["email"], EMAIL)
        self.assertEqual(item["status"], "invited")
        self.assertEqual(self.create().json(), item)
        self.assertEqual(
            self.client.get(API, headers=BEARER).json(), {"items": [item], "nextCursor": None}
        )
        self.assertNotIn("providerMessageId", item)
        self.send.assert_called_once_with(EMAIL, f"workspace-invite/{item['revision']}")

    def test_rejects_other_domains_aliases_and_extra_fields(self):
        for email in ("example+tag@gmail.com", "example@googlemail.com", "example@example.com"):
            with self.subTest(email=email):
                self.assertEqual(self.create(email).status_code, 422)
        self.assertEqual(self.create(role="admin").status_code, 422)
        self.assertEqual(self.create(replaceRevision=None).status_code, 422)
        self.assertEqual(
            self.client.post(API, headers=BEARER, content=b"{" + b"x" * 512).status_code, 415
        )
        self.send.assert_not_called()

    def test_retry_keeps_the_original_provider_idempotency_key(self):
        self.send.side_effect = [DeliveryUnconfirmed, "provider-message"]
        failed = self.create().json()
        self.assertEqual(failed["status"], "send_failed")
        self.assertTrue(failed["canRetry"])
        self.assertFalse(
            invites.admission_allowed(None, self.store.rows[failed["id"]], "google-a", NOW)
        )
        sent = self.action(failed, "retry").json()
        self.assertEqual(sent["status"], "invited")
        self.assertEqual(self.send.call_args_list[0], self.send.call_args_list[1])

    def test_revocation_wins_inflight_delivery_and_reissue_requires_current_revision(self):
        original_send = self.send.return_value

        def revoke_while_sending(_, delivery_key):
            row = self.store.rows[invites.invitation_id(EMAIL)]
            revision = delivery_key.split("/")[-1]
            self.store.change(
                invites.invitation_id(EMAIL), lambda before: invites.revoke(before, NOW, revision)
            )
            self.assertEqual(row["status"], "sending")
            return original_send

        self.send.side_effect = revoke_while_sending
        revoked = self.create().json()
        self.assertEqual(revoked["status"], "revoked")
        self.assertEqual(self.store.rows[revoked["id"]]["providerMessageId"], original_send)
        self.assertEqual(self.create().json(), revoked)
        self.send.side_effect = None
        self.send.return_value = "replacement-message"
        sent = self.create(replaceRevision=revoked["revision"]).json()
        self.assertEqual(sent["status"], "invited")
        self.assertEqual(self.store.rows[sent["id"]]["providerMessageId"], "replacement-message")
        self.assertNotEqual(sent["revision"], revoked["revision"])
        self.assertEqual(self.action(revoked, "revoke").json(), sent)
        self.assertEqual(self.create(replaceRevision=revoked["revision"]).json(), sent)
        self.assertEqual(self.send.call_count, 2)

    def test_late_success_from_the_original_lease_confirms_the_same_retry(self):
        original, _ = invites.start_delivery(None, EMAIL, NOW, "first")
        retry, _ = invites.start_delivery(
            original, None, NOW + invites.DELIVERY_LEASE, "second", "first"
        )
        for current in (
            retry,
            invites.finish_delivery(retry, retry["deliveryKey"], "second", None, NOW + 31)[1],
        ):
            with self.subTest(status=current["status"]):
                _, final = invites.finish_delivery(
                    current, original["deliveryKey"], "first", "confirmed-id", NOW + 32
                )
                self.assertEqual(final["status"], "invited")
                self.assertEqual(final["providerMessageId"], "confirmed-id")
                self.assertEqual(
                    invites.finish_delivery(final, retry["deliveryKey"], "second", None, NOW + 33),
                    (None, final),
                )

    def test_late_receipt_cannot_attach_to_a_reissued_invitation(self):
        original, _ = invites.start_delivery(None, EMAIL, NOW, "first")
        revoked, _ = invites.revoke(original, NOW + 1, "first")
        replacement, _ = invites.start_delivery(revoked, EMAIL, NOW + 2, "second", "first")
        self.assertEqual(
            invites.finish_delivery(
                replacement, original["deliveryKey"], "first", "old-recipient-id", NOW + 3
            ),
            (None, replacement),
        )
        self.assertNotIn("providerMessageId", replacement)

    def test_stale_ambiguous_delivery_cannot_retry_outside_provider_window(self):
        self.send.side_effect = DeliveryUnconfirmed
        failed = self.create().json()
        self.clock.time.return_value += invites.DELIVERY_RETRY_LIFETIME
        self.assertFalse(self.action(failed, "retry").json()["canRetry"])
        self.send.assert_called_once()

    def test_check_leaves_invite_unclaimed_bind_does_not_admit_another_identity(self):
        self.create()
        event = {
            "contractVersion": CONTRACT_VERSION,
            "uid": "firebase-invitee",
            "email": EMAIL,
            "emailVerified": True,
            "provider": "google.com",
            "subject": "google-subject-123",
        }
        headers = {**BEARER, "X-FolioView-Contract": CONTRACT_VERSION}
        response = self.client.post(f"{INTERNAL}/check", headers=headers, json=event)
        self.assertIn(response.status_code, [401, 403, 503])
        workload = self.enterContext(patch.object(invites, "_require_private_workload"))

        def admission(action, **override):
            return self.client.post(
                f"{INTERNAL}/{action}", headers=headers, json={**event, **override}
            )

        self.assertEqual(admission("check").json(), {"admitted": True})
        self.assertEqual(self.store.members, {})
        self.assertEqual(admission("bind", emailVerified=False).status_code, 403)
        self.assertEqual(admission("bind", email="other@gmail.com").json(), {"admitted": False})
        self.assertEqual(admission("bind").json(), {"admitted": True})
        self.assertEqual(admission("bind", uid="second-firebase-uid").json(), {"admitted": False})
        self.assertEqual(
            admission("bind", subject="another-google-subject").json(), {"admitted": False}
        )
        self.assertEqual(admission("bind").json(), {"admitted": True})
        self.assertEqual(workload.call_args.kwargs["caller_env"], "USER_INVITATION_AUTH_CALLER")

    def test_expired_invites_and_inactive_members_are_denied(self):
        row = self.create().json()
        record = self.store.rows[row["id"]]
        self.assertFalse(invites.admission_allowed(None, record, "google-a", row["expiresAt"]))
        self.assertFalse(
            invites.admission_allowed(
                {"state": "inactive", "googleSubject": "google-a"}, record, "google-a", NOW
            )
        )

    def test_direct_private_user_routes_require_membership_only_when_enabled(self):
        self.claims.return_value["uid"] = "firebase-member"
        self.assertEqual(self.client.get("/api/v1/me", headers=BEARER).status_code, 200)
        os.environ["FOLIOCREW_WORKSPACE_ACCESS_RESTRICTED"] = "1"
        for path in (
            "/api/v1/me",
            "/api/v1/watchlist",
            "/api/v1/channel-follows",
            "/api/v1/fx-follows",
        ):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path, headers=BEARER).status_code, 403)
        self.store.members["firebase-member"] = {"state": "active", "googleSubject": "google-a"}
        self.assertEqual(self.client.get("/api/v1/me", headers=BEARER).status_code, 200)
        self.store.members["firebase-member"]["state"] = "inactive"
        self.assertEqual(self.client.get("/api/v1/me", headers=BEARER).status_code, 403)
        self.claims.return_value["uid"] = ADMIN
        self.assertEqual(self.client.get("/api/v1/me", headers=BEARER).status_code, 200)
        self.assertEqual(self.client.get("/health").status_code, 200)


if __name__ == "__main__":
    unittest.main()
