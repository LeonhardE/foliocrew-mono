import base64
import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import main
from firebase_functions.https_fn import FunctionsErrorCode, HttpsError
from flask import Flask, Request
from werkzeug.test import EnvironBuilder

ORIGIN = "https://user-api-123456789.northamerica-northeast2.run.app"
CREATE_AUDIENCE = "https://create-fixture.northamerica-northeast2.run.app"
SIGN_IN_AUDIENCE = "https://signin-fixture.northamerica-northeast2.run.app"
EMAIL = "synthetic.invitee@gmail.com"
TOKEN = "fixture.identity.token"
CALLER = "fixture@fixture.iam.gserviceaccount.com"


def event(**fields):
    data = {
        "uid": "synthetic-firebase-uid",
        "email": EMAIL,
        "email_verified": True,
        "tenant_id": None,
        "disabled": False,
        "provider_data": [
            SimpleNamespace(uid="synthetic-google-uid", email=EMAIL, provider_id="google.com")
        ],
        **fields,
    }
    return SimpleNamespace(
        data=SimpleNamespace(**data),
        additional_user_info=SimpleNamespace(provider_id="google.com"),
    )


def callback(audience, event_type):
    def encode(value):
        return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")

    header = encode({"alg": "RS256", "kid": "synthetic"})
    claims = encode({"aud": audience, "event_type": event_type})
    return Request(
        EnvironBuilder(
            path="/", method="POST", json={"data": {"jwt": f"{header}.{claims}.ZmFrZQ"}}
        ).get_environ()
    )


class WorkspaceAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(
            patch.dict(
                os.environ,
                {
                    "FOLIOCREW_INVITATION_USER_ORIGIN": ORIGIN,
                    "FOLIOCREW_INVITATION_CREATE_AUDIENCE": CREATE_AUDIENCE,
                    "FOLIOCREW_INVITATION_SIGN_IN_AUDIENCE": SIGN_IN_AUDIENCE,
                    "FOLIOCREW_INVITATION_FUNCTION_SERVICE_ACCOUNT": CALLER,
                },
                clear=True,
            )
        )
        self.identity = self.enterContext(patch.object(main, "_workload_token", return_value=TOKEN))
        self.response = self.enterContext(
            patch.object(main, "_response", return_value=b'{"admitted":true}')
        )

    def test_before_create_checks_and_before_sign_in_binds_then_sets_session_claim(self):
        created = main.before_workspace_user_created.__wrapped__.__wrapped__(event())
        self.assertIsNone(created)
        self.assertEqual(
            self.response.call_args.args[2], "/internal/v2/workspace-invitations/check"
        )
        signed_in = main.before_workspace_user_signed_in.__wrapped__.__wrapped__(event())
        self.assertEqual(signed_in, {"session_claims": {"foliocrew_workspace": "admitted-v1"}})
        self.assertEqual(self.response.call_args.args[2], "/internal/v2/workspace-invitations/bind")
        input = self.response.call_args.kwargs
        self.assertEqual(input["headers"]["Authorization"], f"Bearer {TOKEN}")
        self.assertEqual(input["headers"]["X-FolioView-Contract"], main.CONTRACT)
        self.assertEqual(
            json.loads(input["body"]),
            {
                "contractVersion": main.CONTRACT,
                "uid": "synthetic-firebase-uid",
                "subject": "synthetic-google-uid",
                "email": EMAIL,
                "emailVerified": True,
                "provider": "google.com",
            },
        )
        self.identity.assert_called_with(ORIGIN)

    def test_user_request_allows_cold_start_within_callback_budget(self):
        with patch.object(main.http.client, "HTTPSConnection") as connection:
            main._evaluate("check", event())
        connection.assert_called_once_with(
            "user-api-123456789.northamerica-northeast2.run.app", timeout=4.75
        )
        self.assertLess(
            connection.call_args.kwargs["timeout"] + main.METADATA_TIMEOUT_SECONDS,
            main.FUNCTION_OPTIONS["timeout_sec"],
        )

    def test_unverified_wrong_provider_tenant_and_mismatched_email_never_reach_user(self):
        linked = event()
        linked.additional_user_info.provider_id = "password"
        for identity in (
            linked,
            event(email_verified=False),
            event(tenant_id="synthetic-tenant"),
            event(email="different@gmail.com"),
            event(disabled=True),
            event(provider_data=[]),
        ):
            with self.assertRaises(HttpsError) as caught:
                main._evaluate("check", identity)
            self.assertEqual(caught.exception.code, FunctionsErrorCode.PERMISSION_DENIED)
        self.identity.assert_not_called()
        self.response.assert_not_called()

    def test_downstream_denial_and_outage_fail_closed_and_use_generic_errors(self):
        self.response.return_value = b'{"admitted":false}'
        with self.assertRaises(HttpsError) as denied:
            main._evaluate("bind", event())
        self.assertEqual(denied.exception.message, "WORKSPACE_INVITATION_REQUIRED")
        self.response.return_value = b'{"admitted":1}'
        with self.assertRaises(HttpsError) as malformed:
            main._evaluate("bind", event())
        self.assertEqual(malformed.exception.code, FunctionsErrorCode.UNAVAILABLE)
        self.response.side_effect = TimeoutError("private backend diagnostic")
        with self.assertRaises(HttpsError) as timed_out:
            main._evaluate("bind", event())
        self.assertEqual(timed_out.exception.message, "WORKSPACE_ADMISSION_UNAVAILABLE")

    def test_signed_event_boundary_pins_audience_event_type_and_emulator_guard(self):
        sdk = Mock(return_value=main.Response(status=200))
        handler = main._scope_event("beforeCreate", "FOLIOCREW_INVITATION_CREATE_AUDIENCE")(sdk)
        self.assertEqual(handler(callback(SIGN_IN_AUDIENCE, "beforeCreate")).status_code, 403)
        self.assertEqual(handler(callback(CREATE_AUDIENCE, "beforeSignIn")).status_code, 403)
        sdk.assert_not_called()
        self.assertEqual(handler(callback(CREATE_AUDIENCE, "beforeCreate")).status_code, 200)
        sdk.assert_called_once()
        os.environ["FIREBASE_AUTH_EMULATOR_HOST"] = "localhost:9999"
        self.assertEqual(handler(callback(CREATE_AUDIENCE, "beforeCreate")).status_code, 503)
        self.assertEqual(sdk.call_count, 1)

    def test_actual_sdk_routes_do_not_forward_unverified_events(self):
        os.environ["GOOGLE_CLOUD_PROJECT"] = "synthetic-fixture"
        with Flask(__name__).app_context(), self.assertLogs(level="ERROR"):
            response = main.before_workspace_user_created(callback(CREATE_AUDIENCE, "beforeCreate"))
        self.assertGreaterEqual(response.status_code, 400)
        self.identity.assert_not_called()
        self.response.assert_not_called()

    def test_compact_jwt_requires_three_unpadded_base64url_segments(self):
        self.assertTrue(main._is_compact_jwt(b"abc_-12.DEF.123"))
        for token in (b"abc..123", b"abc.DEF.123.", b"abc=.DEF.123", b"abc.DEF+.123"):
            with self.subTest(token=token):
                self.assertFalse(main._is_compact_jwt(token))


if __name__ == "__main__":
    unittest.main()
