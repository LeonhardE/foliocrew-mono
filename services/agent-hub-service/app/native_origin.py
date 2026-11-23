"""Select the branded native origin only after verifying the dedicated edge proof."""

import json
import os
import re
import time
from contextvars import ContextVar
from dataclasses import replace
from urllib.parse import urlsplit

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from starlette.responses import Response

from folioview_shared.encrypted.errors import ContractError
from folioview_shared.encrypted.jsonutil import b64url_decode

from .oauth_config import OAuthConfig

BRAND_ORIGIN = "https://mcp.foliocrew.app"
BRAND_RESOURCE = BRAND_ORIGIN + "/mcp/v3"
BRAND_HOST = b"mcp.foliocrew.app"
PROOF_HEADER = b"x-foliocrew-agent-edge-proof"
PROOF_VERSION = "foliocrew.agent-edge-origin.v1"
PROOF = re.compile(rb"([1-9][0-9]{9})\.([A-Za-z0-9_-]{86})")
GET_PATHS = {
    "/.well-known/oauth-protected-resource/mcp/v3",
    "/.well-known/oauth-authorization-server/oauth/persistent",
    "/oauth/persistent/authorize",
    "/agent/v3/account/consent.html",
    "/agent/v3/runtime/account-consent.html",
    "/agent/v3/account/config",
}
POST_PATHS = {"/mcp/v3", "/oauth/persistent/token", "/oauth/persistent/revoke"}
GET_ASSET = re.compile(
    r"/agent/v3/(?:account/1\.0\.0/(?:consent\.html|account\.css|"
    r"account-consent-page\.mjs|account-bridge\.mjs|integrity\.json)|"
    r"client/(?:1\.0\.[01]|1\.1\.0|1\.2\.0|1\.3\.[0-3])/"
    r"(?:client\.mjs|integrity\.json|THIRD_PARTY_NOTICES\.md))"
)
ACCOUNT_FLOW = re.compile(
    r"/api/v2/persistent-account-authorizations/native_request_[A-Za-z0-9_-]{43}/"
    r"(?:pending|approvals)"
)
RUNTIME = re.compile(
    r"/agent/v3/persistent/owners/[A-Za-z0-9_-]{1,128}/vaults/[A-Za-z0-9_-]{1,128}/"
    r"connections/[A-Za-z0-9_-]{1,128}/(?:session|consent-receipts|tasks|task-input|"
    r"runs/(?:begin|receipt|input|submit|result-receipt)|plans/(?:state|report)|"
    r"task-center/(?:context|prepare|plans/report|manual/query))"
)
_branded_request = ContextVar("branded_native_request", default=False)


def branded_native_request():
    return _branded_request.get()


def _key():
    return Ed25519PublicKey.from_public_bytes(
        b64url_decode(os.getenv("HUB_NATIVE_EDGE_PUBLIC_KEY", ""), exact_bytes=32)
    )


def native_oauth_configuration(*, branded=None):
    """The existing public origin remains the default for unmarked traffic."""
    primary = OAuthConfig.environment()
    if branded is None:
        branded = branded_native_request()
    if not branded:
        return primary, primary.issuer
    _key()
    if primary.issuer == BRAND_ORIGIN:
        raise ContractError("authorization_unavailable")
    consent_path = urlsplit(primary.consent_url).path
    return replace(
        primary, issuer=BRAND_ORIGIN, consent_url=BRAND_ORIGIN + consent_path
    ), primary.issuer


def _allowed(method, path):
    if method == "GET":
        return path in GET_PATHS or GET_ASSET.fullmatch(path) is not None
    return method == "POST" and (
        path in POST_PATHS
        or ACCOUNT_FLOW.fullmatch(path) is not None
        or RUNTIME.fullmatch(path) is not None
    )


class AgentEdgeIngress:
    def __init__(self, app, *, clock=time.time):
        self.app = app
        self.clock = clock

    def _branded_scope(self, scope, headers, proof):
        claim = PROOF.fullmatch(proof)
        if claim is None or abs(int(self.clock()) - int(claim[1])) > 30:
            raise ValueError
        config = OAuthConfig.environment()
        if config.issuer == BRAND_ORIGIN:
            raise ValueError
        host = urlsplit(config.issuer).netloc.encode("ascii")
        if headers.get(b"host") != [host] or len(headers.get(b"origin", ())) > 1:
            raise ValueError
        raw_path = scope["raw_path"].decode("ascii")
        query = scope["query_string"].decode("ascii")
        if raw_path != scope["path"] or len(query) > 8192:
            raise ValueError
        target = raw_path + ("?" + query if query else "")
        origin = headers[b"origin"][0].decode("ascii") if b"origin" in headers else None
        message = json.dumps(
            [
                PROOF_VERSION,
                claim[1].decode(),
                config.issuer,
                BRAND_ORIGIN,
                scope["method"],
                target,
                origin,
            ],
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
        _key().verify(b64url_decode(claim[2].decode(), exact_bytes=64), message)
        forwarded = [
            (name, value)
            for name, value in scope["headers"]
            if name.lower() not in {PROOF_HEADER, b"host"}
        ]
        return {
            **scope,
            "headers": [*forwarded, (b"host", BRAND_HOST)],
            "scheme": "https",
            "server": (BRAND_HOST.decode(), 443),
        }

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {}
        for name, value in scope["headers"]:
            headers.setdefault(name.lower(), []).append(value)
        proofs = headers.get(PROOF_HEADER)
        if not proofs and BRAND_HOST not in headers.get(b"host", ()):
            await self.app(scope, receive, send)
            return
        try:
            if not proofs or len(proofs) != 1:
                raise ValueError
            branded = self._branded_scope(scope, headers, proofs[0])
        except (ContractError, InvalidSignature, KeyError, ValueError):
            await Response(status_code=403, headers={"Cache-Control": "no-store"})(
                scope, receive, send
            )
            return
        if not _allowed(scope["method"], scope["path"]):
            await Response(status_code=404, headers={"Cache-Control": "no-store"})(
                scope, receive, send
            )
            return
        context = _branded_request.set(True)
        try:
            await self.app(branded, receive, send)
        finally:
            _branded_request.reset(context)
