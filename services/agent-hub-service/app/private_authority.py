"""Bound User authority delegations for an explicitly transferred account."""

import hashlib
import os
import re
import time

from folioview_shared.delegation import PRIVATE_AUTHORITY_DELEGATION_TYPE
from folioview_shared.encrypted.constants import CONTRACT_VERSION
from folioview_shared.encrypted.errors import ContractError
from folioview_shared.encrypted.jsonutil import canonical_json
from folioview_shared.encrypted.private_resources import (
    PRIVATE_AUTHORITY_PROFILE,
    private_authority_lookup,
)
from folioview_shared.identity import owner_key

from .signing import get_signer, token_configuration
from .store import private_resource_writer_fence_path

PORTFOLIO_PATH = "/internal/v2/private-resources/portfolio-authority/read"
_HUB_NUMBERED_ORIGIN = re.compile(
    r"https://agent-hub-api-([1-9][0-9]{5,19}\.[a-z][a-z0-9-]*[0-9]\.run\.app)\Z"
)


def transferred_writer(unit, owner, vault):
    fence = unit.get(private_resource_writer_fence_path(owner))
    return (
        fence is not None
        and fence.get("ownerSubject") == owner
        and fence.get("vaultId") == vault
        and fence.get("state") == "transferred"
        and type(fence.get("writerEpoch")) is int
        and fence["writerEpoch"] == 2
    )


def numbered_user_origin(issuer, configured):
    deployment = _HUB_NUMBERED_ORIGIN.fullmatch(issuer)
    if deployment is None or configured != "https://user-api-" + deployment[1]:
        raise ContractError("authorization_unavailable")
    return configured


def issue_portfolio_authority_token(store, uid, vault, value):
    owner = owner_key(uid)
    if (
        os.getenv("HUB_PORTFOLIO_USER_AUTHORITY_TOKENS") != "1"
        or os.getenv("HUB_USER_PRIVATE_AUTHORITY_OWNER") != owner
    ):
        raise ContractError("not_found")
    lookup = private_authority_lookup(
        {
            **value,
            "profile": PRIVATE_AUTHORITY_PROFILE,
            "consumer": "portfolio",
            "ownerSubject": owner,
            "vaultId": vault,
        }
    )
    if not store.transact(lambda unit: transferred_writer(unit, owner, vault)):
        raise ContractError("not_found")
    issuer, caller = token_configuration()
    user_origin = numbered_user_origin(issuer, os.getenv("HUB_USER_ORIGIN", ""))
    now = int(time.time())
    claims = {
        "iss": issuer,
        "aud": user_origin + PORTFOLIO_PATH,
        "sub": uid,
        "iat": now,
        "exp": now + 60,
        "jti": lookup["nonce"],
        "caller": caller,
        "purpose": "private_authority_read",
        "requestDigest": hashlib.sha256(canonical_json(lookup)).hexdigest(),
    }
    return {
        "contractVersion": CONTRACT_VERSION,
        "token": get_signer().sign(claims, typ=PRIVATE_AUTHORITY_DELEGATION_TYPE),
        "expiresAt": claims["exp"],
    }
