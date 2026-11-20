"""Firebase Google sign-in blocking functions for the invited workspace."""

import http.client
import json
import os
import re
from functools import wraps
from typing import Literal
from urllib.parse import urlencode, urlsplit

from firebase_functions import identity_fn
from firebase_functions.https_fn import FunctionsErrorCode, HttpsError
from flask import Response
from google.auth import jwt

CONTRACT = "folioview.agent-workspace.v2.0"
GOOGLE = "google.com"
USER_ORIGIN = re.compile(r"https://user-api-[0-9]{1,20}\.[a-z]+(?:-[a-z0-9]+)+[0-9]\.run\.app")
FUNCTION_ORIGIN = re.compile(r"https://[a-z0-9.-]+\.run\.app")
JWT = re.compile(rb"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")
ACTION = Literal["check", "bind"]
FUNCTION_OPTIONS = {
    "region": "northamerica-northeast2",
    "timeout_sec": 6,
    "max_instances": 3,
    "service_account": os.getenv("FOLIOCREW_INVITATION_FUNCTION_SERVICE_ACCOUNT"),
    "id_token": False,
    "access_token": False,
    "refresh_token": False,
}


class AdmissionUnavailable(Exception):
    """The User service could not confirm workspace admission."""


def _deny() -> HttpsError:
    return HttpsError(FunctionsErrorCode.PERMISSION_DENIED, "WORKSPACE_INVITATION_REQUIRED")


def _scope_event(event_type: str, audience_var: str):
    def decorator(handler):
        @wraps(handler)
        def scoped(request):
            audience = os.getenv(audience_var, "")
            if (
                not FUNCTION_ORIGIN.fullmatch(audience)
                or os.getenv("FIREBASE_AUTH_EMULATOR_HOST")
                or not os.getenv("FOLIOCREW_INVITATION_FUNCTION_SERVICE_ACCOUNT")
            ):
                return Response(status=503)
            if request.content_length is None or request.content_length > 16_384:
                return Response(status=400)
            try:
                token = request.get_json()["data"]["jwt"]
                if (
                    not isinstance(token, str)
                    or not token.isascii()
                    or not JWT.fullmatch(token.encode())
                ):
                    return Response(status=403)
                claims = jwt.decode(token, verify=False)
                if claims.get("aud") != audience or claims.get("event_type") != event_type:
                    return Response(status=403)
            except (KeyError, TypeError, ValueError):
                return Response(status=403)
            # The SDK verifies the signature, project, issuer and expiration on the same
            # request before accessing the signed identity or calling the User service.
            return handler(request)

        return scoped

    return decorator


def _response(connection, method, path, *, body=None, headers=None, maximum, contract=False):
    try:
        connection.request(method, path, body=body, headers=headers or {})
        result = connection.getresponse()
        if result.status != 200 or (
            contract and result.getheader("X-FolioView-Contract") != CONTRACT
        ):
            raise AdmissionUnavailable
        raw = result.read(maximum + 1)
        if len(raw) > maximum:
            raise AdmissionUnavailable
        return raw
    finally:
        connection.close()


def _workload_token(origin: str) -> str:
    metadata = http.client.HTTPConnection("metadata.google.internal", timeout=0.75)
    query = urlencode({"audience": origin, "format": "full"})
    token = _response(
        metadata,
        "GET",
        "/computeMetadata/v1/instance/service-accounts/default/identity?" + query,
        headers={"Metadata-Flavor": "Google"},
        maximum=8192,
    )
    if not JWT.fullmatch(token):
        raise AdmissionUnavailable
    return token.decode("ascii")


def _evaluate(operation: ACTION, event: identity_fn.AuthBlockingEvent) -> None:
    user = event.data
    email = user.email
    if (
        event.additional_user_info.provider_id != GOOGLE
        or user.tenant_id is not None
        or user.disabled
        or user.email_verified is not True
        or not isinstance(email, str)
        or not email
    ):
        raise _deny()
    google = [info for info in user.provider_data if info.provider_id == GOOGLE]
    if len(google) != 1 or (
        not google[0].uid
        or not isinstance(google[0].email, str)
        or google[0].email.lower() != email.lower()
    ):
        raise _deny()

    origin = os.getenv("FOLIOCREW_INVITATION_USER_ORIGIN", "")
    if not USER_ORIGIN.fullmatch(origin):
        raise HttpsError(FunctionsErrorCode.UNAVAILABLE, "WORKSPACE_ADMISSION_UNAVAILABLE")
    try:
        token = _workload_token(origin)
        downstream = http.client.HTTPSConnection(urlsplit(origin).hostname, timeout=3.25)
        raw = _response(
            downstream,
            "POST",
            f"/internal/v2/workspace-invitations/{operation}",
            body=json.dumps(
                {
                    "contractVersion": CONTRACT,
                    "uid": user.uid,
                    "email": email,
                    "emailVerified": True,
                    "provider": GOOGLE,
                    "subject": google[0].uid,
                }
            ).encode(),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "X-FolioView-Contract": CONTRACT,
            },
            maximum=128,
            contract=True,
        )
        result = json.loads(raw)
        if (
            type(result) is not dict
            or set(result) != {"admitted"}
            or type(result["admitted"]) is not bool
        ):
            raise AdmissionUnavailable
    except (AdmissionUnavailable, ValueError, OSError, http.client.HTTPException):
        raise HttpsError(
            FunctionsErrorCode.UNAVAILABLE, "WORKSPACE_ADMISSION_UNAVAILABLE"
        ) from None
    if not result["admitted"]:
        raise _deny()


@_scope_event("beforeCreate", "FOLIOCREW_INVITATION_CREATE_AUDIENCE")
@identity_fn.before_user_created(**FUNCTION_OPTIONS)
def before_workspace_user_created(
    event: identity_fn.AuthBlockingEvent,
) -> identity_fn.BeforeCreateResponse | None:
    _evaluate("check", event)


@_scope_event("beforeSignIn", "FOLIOCREW_INVITATION_SIGN_IN_AUDIENCE")
@identity_fn.before_user_signed_in(**FUNCTION_OPTIONS)
def before_workspace_user_signed_in(
    event: identity_fn.AuthBlockingEvent,
) -> identity_fn.BeforeSignInResponse:
    _evaluate("bind", event)
    return {"session_claims": {"foliocrew_workspace": "admitted-v1"}}
