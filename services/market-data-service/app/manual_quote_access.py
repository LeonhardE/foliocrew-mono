"""Workspace authentication for manual quote refreshes only."""

import os
import re
import time
from functools import lru_cache

from fastapi import HTTPException, Request

from folioview_shared.delegated_keys import KeyCache
from folioview_shared.service_identity import (
    IdentityVerificationUnavailable,
    InvalidIdentityToken,
    verify_signed_jwt,
)

FIREBASE_KEYS = (
    "https://www.googleapis.com/service_accounts/v1/jwk/securetoken@system.gserviceaccount.com"
)
PROJECT = re.compile(r"[a-z][a-z0-9-]{4,28}[a-z0-9]")


@lru_cache(maxsize=1)
def firebase_keys():
    return KeyCache(FIREBASE_KEYS)


def require_manual_quote_user(request: Request) -> None:
    authorizations = request.headers.getlist("authorization")
    if len(authorizations) != 1 or not authorizations[0].startswith("Bearer "):
        raise HTTPException(
            401, "Sign in to refresh quotes.", headers={"WWW-Authenticate": "Bearer"}
        )
    project = os.getenv("FIREBASE_PROJECT_ID", "")
    if not PROJECT.fullmatch(project):
        raise HTTPException(503, "Quote refresh sign-in is unavailable.")
    try:
        claims = verify_signed_jwt(
            authorizations[0][7:],
            keys=firebase_keys(),
            expected_typ="JWT",
            maximum_bytes=8192,
            require_typ=False,
        )
    except InvalidIdentityToken:
        raise HTTPException(
            401, "Sign in to refresh quotes.", headers={"WWW-Authenticate": "Bearer"}
        ) from None
    except IdentityVerificationUnavailable:
        raise HTTPException(503, "Quote refresh sign-in is unavailable.") from None

    now = time.time()
    issued, expires, auth_time = (claims.get(key) for key in ("iat", "exp", "auth_time"))
    subject, firebase = claims.get("sub"), claims.get("firebase")
    if (
        claims.get("aud") != project
        or claims.get("iss") != f"https://securetoken.google.com/{project}"
        or not isinstance(subject, str)
        or not 1 <= len(subject) <= 128
        or any(type(value) is not int for value in (issued, expires, auth_time))
        or not 0 <= auth_time <= issued <= now < expires <= issued + 3600
        or type(firebase) is not dict
        or firebase.get("sign_in_provider") != "google.com"
    ):
        raise HTTPException(
            401, "Sign in to refresh quotes.", headers={"WWW-Authenticate": "Bearer"}
        )
    if claims.get("foliocrew_workspace") != "admitted-v1":
        raise HTTPException(403, "Workspace access is required to refresh quotes.")
