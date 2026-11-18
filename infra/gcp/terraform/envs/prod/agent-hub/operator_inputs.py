"""Private full-Hub input validation only; never runs Terraform or cloud operations."""

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from deployment_profile import ProfileError, browser_origin_aliases  # noqa: E402

FLAGS = ("provider_connection_slots_enabled", "task_center_enabled")
FIELDS = {
    "deployment",
    "bootstrap_image",
    "sources",
    "connector",
    "persistent_mode_enabled",
    "agent_owned_allowed_owner_subjects",
    "agent_owned_mode_enabled",
    "agent_clients",
    "browser_origin_aliases",
    *FLAGS,
}
DEPLOYMENT = {
    "project_id",
    "region",
    "artifact_repository",
    "runtime_account_id",
    "creation_image",
    "web_origin",
    "hub_origin",
}
SOURCES = {
    "user_origin",
    "portfolio_origin",
    "portfolio_caller_email",
    "trusted_portfolio_callers",
}
CLIENT = {"client_id", "redirect_uris", "token_endpoint_auth_method", "secret_sha256"}


class InputError(ValueError):
    """Fixed diagnostic code only, never an input value or unknown member name."""


def require(condition, code):
    if not condition:
        raise InputError(code)


def fields(value, allowed, required=()):
    require(type(value) is dict, "invalid_object")
    require(set(value) <= allowed and set(required) <= set(value), "unexpected_fields")


def unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate_member")
        result[key] = value
    return result


def reject_constant(_value):
    raise InputError("invalid_json")


def decode_input(raw):
    require(type(raw) is bytes, "input_bytes_required")
    try:
        value = json.loads(
            raw.decode("utf-8"), object_pairs_hook=unique_pairs, parse_constant=reject_constant
        )
    except (UnicodeError, ValueError, RecursionError):
        raise InputError("invalid_json") from None
    fields(value, FIELDS, {"deployment"})
    return value


def boolean(value, name):
    result = value.get(name, False)
    require(type(result) is bool, "invalid_boolean")
    return result


def clients(value, *, legacy=False):
    require(type(value) is list, "invalid_clients")
    for client in value:
        fields(
            client,
            CLIENT if legacy else CLIENT | {"provider"},
            {"client_id", "redirect_uris"} | (set() if legacy else {"provider"}),
        )
        require(type(client["client_id"]) is str and bool(client["client_id"]), "invalid_client")
        if not legacy:
            require(client["provider"] in ("muse", "chatgpt"), "invalid_provider")
        redirects = client["redirect_uris"]
        require(
            type(redirects) is list
            and 1 <= len(redirects) <= 4
            and all(type(uri) is str and uri for uri in redirects),
            "invalid_callbacks",
        )
        method = client.get("token_endpoint_auth_method")
        require(method is None or type(method) is str, "invalid_client")
        method = "none" if method is None else method
        require(method in ("none", "client_secret_basic"), "invalid_client")
        secret = client.get("secret_sha256")
        require(
            secret is None or (type(secret) is str and re.fullmatch(r"[a-f0-9]{64}", secret)),
            "invalid_client",
        )
        require(
            (method == "none" and secret is None)
            or (method == "client_secret_basic" and secret is not None),
            "invalid_client",
        )
    return value


def validate_full_input(value):
    fields(value, FIELDS, {"deployment"})
    deployment = value["deployment"]
    fields(deployment, DEPLOYMENT, DEPLOYMENT)
    require(all(type(v) is str and v for v in deployment.values()), "invalid_deployment")
    require(
        value.get("bootstrap_image") in (None, deployment["creation_image"]),
        "conflicting_creation_image",
    )
    sources = value.get("sources", {})
    fields(sources, SOURCES)
    for key in SOURCES - {"trusted_portfolio_callers"}:
        require(sources.get(key) is None or type(sources[key]) is str, "invalid_sources")
    aliases = value.get("browser_origin_aliases", [])
    require(type(aliases) is list, "invalid_browser_origins")
    if aliases:
        reserved = {
            deployment["web_origin"],
            deployment["hub_origin"],
            sources.get("user_origin"),
            sources.get("portfolio_origin"),
        }
        try:
            browser_origin_aliases(aliases, reserved)
        except ProfileError:
            raise InputError("invalid_browser_origins") from None
    trusted = sources.get("trusted_portfolio_callers", {})
    trusted = {} if trusted is None else trusted
    require(
        type(trusted) is dict
        and len(trusted) <= 1
        and all(type(k) is str and type(v) is str for k, v in trusted.items()),
        "invalid_sources",
    )
    connector = value.get("connector", {})
    fields(connector, {"oauth_enabled", "encrypted_adapter_enabled", "muse_clients"})
    oauth = boolean(connector, "oauth_enabled")
    require(not boolean(connector, "encrypted_adapter_enabled"), "retired_adapter")
    require(not boolean(value, "persistent_mode_enabled"), "retired_mode")
    legacy = connector.get("muse_clients", [])
    legacy = clients([] if legacy is None else legacy, legacy=True)
    registered = clients(value.get("agent_clients", []))
    combined = legacy + registered
    require(
        len(combined) <= 8 and len({c["client_id"] for c in combined}) == len(combined),
        "invalid_clients",
    )
    require(not oauth or bool(combined), "missing_registration")
    owners = value.get("agent_owned_allowed_owner_subjects", [])
    require(
        type(owners) is list
        and len(owners) <= 32
        and all(type(owner) is str and re.fullmatch(r"[a-f0-9]{64}", owner) for owner in owners),
        "invalid_owner_scope",
    )
    require(len(set(owners)) == len(owners), "invalid_owner_scope")
    mode = boolean(value, "agent_owned_mode_enabled")
    require(
        not mode
        or (
            owners
            and oauth
            and combined
            and all(sources.get(k) for k in SOURCES - {"trusted_portfolio_callers"})
            and trusted
        ),
        "missing_mode_prerequisites",
    )
    slots, task_center = (boolean(value, name) for name in FLAGS)
    require(not slots or mode, "missing_slot_prerequisite")
    require(not task_center or (slots and mode), "missing_task_prerequisite")


def compare_rollout_inputs(
    baseline_raw, candidate_raw, expected_baseline_sha256, owner_subject=None
):
    require(type(baseline_raw) is bytes and type(candidate_raw) is bytes, "input_bytes_required")
    require(
        type(expected_baseline_sha256) is str
        and re.fullmatch(r"[a-f0-9]{64}", expected_baseline_sha256),
        "invalid_baseline_digest",
    )
    require(
        hashlib.sha256(baseline_raw).hexdigest() == expected_baseline_sha256,
        "baseline_digest_mismatch",
    )
    baseline, candidate = decode_input(baseline_raw), decode_input(candidate_raw)
    validate_full_input(baseline)
    validate_full_input(candidate)
    require(
        {k: v for k, v in baseline.items() if k not in FLAGS}
        == {k: v for k, v in candidate.items() if k not in FLAGS},
        "protected_inputs_changed",
    )
    require(
        owner_subject is None
        or (type(owner_subject) is str and re.fullmatch(r"[a-f0-9]{64}", owner_subject)),
        "invalid_membership_query",
    )
    return {
        "baselineSha256": expected_baseline_sha256,
        "candidateSha256": hashlib.sha256(candidate_raw).hexdigest(),
        "typesValid": True,
        "protectedInputsUnchanged": True,
        "localOwnerMembership": None
        if owner_subject is None
        else owner_subject in candidate.get("agent_owned_allowed_owner_subjects", []),
        "productionMembershipVerified": False,
        "flags": {
            name: {"before": baseline.get(name, False), "after": candidate.get(name, False)}
            for name in FLAGS
        },
        "activationAuthorized": False,
    }


class PrivateArguments(argparse.ArgumentParser):
    def error(self, message):
        raise InputError("invalid_arguments")


def main():
    try:
        parser = PrivateArguments(description=__doc__)
        parser.add_argument("--baseline", type=Path, required=True)
        parser.add_argument("--candidate", type=Path, required=True)
        parser.add_argument("--expected-baseline-sha256", required=True)
        parser.add_argument("--owner-subject")
        args = parser.parse_args()
        result = compare_rollout_inputs(
            args.baseline.read_bytes(),
            args.candidate.read_bytes(),
            args.expected_baseline_sha256,
            args.owner_subject,
        )
        print(json.dumps(result, sort_keys=True))
    except (InputError, OSError) as error:
        print(
            json.dumps(
                {"error": str(error) if isinstance(error, InputError) else "input_unavailable"}
            )
        )
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
