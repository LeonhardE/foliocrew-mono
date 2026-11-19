"""A bounded, request-scoped Hub call to the User report source authority."""

import hashlib
import os
import re
import time

import httpx

from folioview_shared.delegation import REPORT_DELEGATION_TYPE
from folioview_shared.encrypted.constants import CONTRACT_VERSION
from folioview_shared.encrypted.errors import ContractError
from folioview_shared.encrypted.jsonutil import canonical_json, strict_json_loads
from folioview_shared.encrypted.private_resources import report_source_request
from folioview_shared.identity import owner_key

from .catalogue import _JWT, bounded_bytes, remaining, workload_token
from .signing import _EMAIL, get_signer, origin

_PATH = "/internal/v2/private-resources/report-source-decisions"
_USER_ORIGIN = re.compile(r"https://user-api-[0-9]{1,20}\.[a-z]+(?:-[a-z0-9]+)+[0-9]\.run\.app\Z")
_MAX_DECISION_BYTES = 8192
_DEADLINE_SECONDS = 8


class UserReportSourceAuthority:
    def __init__(
        self,
        *,
        issuer,
        caller,
        user_origin,
        signer_factory=get_signer,
        token_factory=workload_token,
        transport=None,
        clock=time.monotonic,
        wall_clock=time.time,
    ):
        self.issuer, self.caller, self.user_origin = issuer, caller, user_origin
        self.signer_factory, self.token_factory = signer_factory, token_factory
        self.transport, self.clock, self.wall_clock = transport, clock, wall_clock

    def decide(self, uid, value):
        request = report_source_request(value)
        if owner_key(uid) != request["ownerSubject"]:
            raise ContractError("insufficient_scope")
        deadline = self.clock() + _DEADLINE_SECONDS
        try:
            issuer = origin(self.issuer)
            if (
                _USER_ORIGIN.fullmatch(self.user_origin) is None
                or self.user_origin == issuer
                or _EMAIL.fullmatch(self.caller) is None
            ):
                raise ContractError("source_unavailable")
            raw = canonical_json(request)
            now = int(self.wall_clock())
            if now < 0:
                raise ContractError("source_unavailable")
            workload = self.token_factory(self.user_origin, deadline=deadline, clock=self.clock)
            delegation = self.signer_factory().sign(
                {
                    "iss": issuer,
                    "aud": self.user_origin + _PATH,
                    "sub": uid,
                    "iat": now,
                    "exp": now + 60,
                    "jti": request["attemptId"],
                    "caller": self.caller,
                    "purpose": "report_source_decision",
                    "requestDigest": hashlib.sha256(raw).hexdigest(),
                },
                typ=REPORT_DELEGATION_TYPE,
                deadline=deadline,
                budget_clock=self.clock,
            )
            if any(
                type(token) is not str or len(token) > 16384 or _JWT.fullmatch(token) is None
                for token in (workload, delegation)
            ):
                raise ContractError("source_unavailable")
            with httpx.Client(
                trust_env=False,
                follow_redirects=False,
                transport=self.transport,
            ) as client:
                with client.stream(
                    "POST",
                    self.user_origin + _PATH,
                    headers={
                        "Authorization": "Bearer " + workload,
                        "X-FolioView-Delegation": delegation,
                        "X-FolioView-Contract": CONTRACT_VERSION,
                        "Content-Type": "application/json",
                        "Cache-Control": "no-store",
                        "Accept-Encoding": "identity",
                    },
                    content=raw,
                    timeout=remaining(deadline, self.clock),
                ) as response:
                    if (
                        response.status_code != 200
                        or response.headers.get("content-type", "").split(";", 1)[0].lower()
                        != "application/json"
                        or response.headers.get("x-folioview-contract") != CONTRACT_VERSION
                    ):
                        raise ContractError("source_unavailable")
                    return strict_json_loads(
                        bounded_bytes(response, deadline, self.clock, maximum=_MAX_DECISION_BYTES),
                        max_bytes=_MAX_DECISION_BYTES,
                    )
        except (ContractError, httpx.HTTPError, TypeError, ValueError, OverflowError):
            raise ContractError("source_unavailable") from None


def get_report_source_authority():
    if os.getenv("HUB_REPORT_SOURCE_AUTHORITY_ENABLED") != "1":
        return None
    return UserReportSourceAuthority(
        issuer=os.getenv("HUB_SERVICE_AUDIENCE", ""),
        caller=os.getenv("HUB_CATALOGUE_CALLER_EMAIL", ""),
        user_origin=os.getenv("HUB_USER_ORIGIN", ""),
    )
