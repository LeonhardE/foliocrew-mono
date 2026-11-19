"""Fixed User origin, exact signed bindings and bounded report decision transport."""

import hashlib
import json
import unittest

import httpx
from fixtures import UID
from test_signing import EMAIL, ISSUER, KEY, NOW, KMSRpc

from app.report_source_authority import UserReportSourceAuthority
from app.signing import KMSSigner
from folioview_shared.delegated_keys import KeyCache
from folioview_shared.delegation import REPORT_DELEGATION_TYPE
from folioview_shared.encrypted.constants import CONTRACT_VERSION
from folioview_shared.encrypted.errors import ContractError
from folioview_shared.encrypted.jsonutil import canonical_json
from folioview_shared.encrypted.private_resources import (
    REPORT_PROFILE,
    decide_report_sources,
    require_report_source_permit,
)
from folioview_shared.identity import owner_key
from folioview_shared.service_identity import verify_signed_jwt

ORIGIN = "https://user-api-123456789.northamerica-northeast2.run.app"
PATH = "/internal/v2/private-resources/report-source-decisions"
REQUEST = {
    "contractVersion": CONTRACT_VERSION,
    "profile": REPORT_PROFILE,
    "purpose": "report_submit",
    "ownerSubject": owner_key(UID),
    "vaultId": "vault_A",
    "connectionId": "connection_A",
    "runId": "run_A",
    "operationId": "synthetic_report_operation_001",
    "attemptId": "synthetic_report_attempt_00001",
    "manifestFingerprint": "a" * 64,
    "reportFingerprint": "b" * 64,
    "resources": [],
}


class UserReportSourceClientTests(unittest.TestCase):
    def setUp(self):
        self.signer = KMSSigner(KEY, client=KMSRpc(), clock=lambda: 100)
        self.calls = []

    def client(self, transport, **options):
        return UserReportSourceAuthority(
            **({"issuer": ISSUER, "caller": EMAIL, "user_origin": ORIGIN} | options),
            signer_factory=lambda: self.signer,
            token_factory=self.workload,
            transport=httpx.MockTransport(transport),
            clock=lambda: 100,
            wall_clock=lambda: NOW,
        )

    def workload(self, audience, *, deadline, clock):
        self.calls.append(audience)
        self.assertEqual(clock(), 100)
        self.assertEqual(deadline, 108)
        return "fixture.workload.signature"

    def test_signed_request_and_fixed_origin_match_user_verification(self):
        def receive(request):
            self.assertEqual(str(request.url), ORIGIN + PATH)
            self.assertEqual(request.method, "POST")
            self.assertEqual(request.headers["authorization"], "Bearer fixture.workload.signature")
            self.assertEqual(request.headers["x-folioview-contract"], CONTRACT_VERSION)
            self.assertEqual(request.content, canonical_json(REQUEST))
            cache = KeyCache(
                ISSUER + "/.well-known/jwks.json",
                transport=lambda *a, **k: json.dumps(self.signer.jwks()).encode(),
            )
            claims = verify_signed_jwt(
                request.headers["x-folioview-delegation"],
                keys=cache,
                expected_typ=REPORT_DELEGATION_TYPE,
            )
            self.assertEqual(
                claims,
                {
                    "iss": ISSUER,
                    "aud": ORIGIN + PATH,
                    "caller": EMAIL,
                    "sub": UID,
                    "iat": NOW,
                    "exp": NOW + 60,
                    "jti": REQUEST["attemptId"],
                    "purpose": "report_source_decision",
                    "requestDigest": hashlib.sha256(request.content).hexdigest(),
                },
            )
            return httpx.Response(
                200,
                headers={"X-FolioView-Contract": CONTRACT_VERSION},
                json=decide_report_sources(
                    REQUEST,
                    snapshot={
                        "ownerSubject": REQUEST["ownerSubject"],
                        "vaultId": REQUEST["vaultId"],
                        "resources": [],
                    },
                    now=NOW,
                ),
            )

        decision = self.client(receive).decide(UID, REQUEST)
        require_report_source_permit(decision, request=REQUEST, now=NOW)
        self.assertEqual(self.calls, [ORIGIN])

    def test_no_cross_owner_or_unpinned_origin_call_and_no_redirect_retry(self):
        def unused(_):
            self.fail("An invalid destination or Owner reached the network.")

        with self.assertRaisesRegex(ContractError, "insufficient_scope"):
            self.client(unused).decide("somebody_else", REQUEST)
        with self.assertRaisesRegex(ContractError, "source_unavailable"):
            self.client(unused, user_origin=ORIGIN + "/different").decide(UID, REQUEST)
        self.assertEqual(self.calls, [])

        urls = []

        def redirect(request):
            urls.append(str(request.url))
            return httpx.Response(307, headers={"Location": "https://outside.invalid"})

        with self.assertRaisesRegex(ContractError, "source_unavailable"):
            self.client(redirect).decide(UID, REQUEST)
        self.assertEqual(urls, [ORIGIN + PATH])
