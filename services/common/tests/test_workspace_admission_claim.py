"""Check admission after, and independently of, Firebase identity verification."""

import os
import unittest
from importlib.util import find_spec
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from starlette.requests import Request

if find_spec("firebase_admin") is not None:
    from folioview_shared import auth
else:
    auth = None


@unittest.skipIf(auth is None, "Private identity consumers supply the Firebase SDK")
class WorkspaceAdmissionClaimTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.dict(os.environ, {}, clear=True))
        self.firebase = self.enterContext(patch.object(auth, "_get_firebase_app")).return_value
        self.verifier = self.enterContext(
            patch.object(
                auth.auth,
                "verify_id_token",
                return_value={"uid": "fixture", "firebase": {"sign_in_provider": "google.com"}},
            )
        )
        self.credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="test-token")

    def verify(self, headers=None):
        request = Request(
            {
                "type": "http",
                "headers": [(b"authorization", b"Bearer test-token"), *(headers or [])],
            }
        )
        return auth.require_google_user(request, self.credentials)

    def test_existing_firebase_session_is_accepted_before_opt_in(self):
        self.assertEqual(self.verify().uid, "fixture")
        self.verifier.assert_called_once_with("test-token", app=self.firebase, check_revoked=True)

    def test_missing_or_modified_claim_and_spoofed_header_do_not_grant_access(self):
        os.environ["FOLIOCREW_REQUIRE_ADMISSION_CLAIM"] = "1"
        for invalid in (None, False, True, "admitted", {"version": "admitted-v1"}):
            with self.subTest(invalid=invalid), self.assertRaises(HTTPException) as failure:
                self.verifier.return_value["foliocrew_workspace"] = invalid
                self.verify([(b"foliocrew_workspace", b"admitted-v1")])
            self.assertEqual(failure.exception.status_code, 403)
            self.assertEqual(failure.exception.headers, {"Cache-Control": "no-store"})

    def test_valid_claim_does_not_replace_revocation_or_google_checks(self):
        os.environ["FOLIOCREW_REQUIRE_ADMISSION_CLAIM"] = "1"
        self.verifier.return_value["foliocrew_workspace"] = "admitted-v1"
        self.assertEqual(self.verify().uid, "fixture")
        self.verifier.return_value["firebase"]["sign_in_provider"] = "password"
        with self.assertRaises(HTTPException) as failure:
            self.verify()
        self.assertEqual(failure.exception.status_code, 401)
        self.verifier.side_effect = auth.auth.RevokedIdTokenError("revoked")
        with self.assertRaises(HTTPException) as revoked:
            self.verify()
        self.assertEqual(revoked.exception.status_code, 401)


if __name__ == "__main__":
    unittest.main()
