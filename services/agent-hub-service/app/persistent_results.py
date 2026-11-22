"""Ciphertext-only persistent reports, durable receipts and owner-isolated history."""

import copy
import re
from uuid import uuid4

from folioview_shared.encrypted.authority import verify_control_command
from folioview_shared.encrypted.budgets import check_read_response
from folioview_shared.encrypted.constants import CONTRACT_VERSION
from folioview_shared.encrypted.crypto import _signed_parts, signing_input_fingerprint
from folioview_shared.encrypted.errors import ContractError
from folioview_shared.encrypted.jsonutil import canonical_json, strict_json_loads
from folioview_shared.encrypted.persistent_content import (
    CONTENT_PROFILE,
    PersistentEnvelopeExpectation,
    digest,
    inspect_persistent_carrier,
    validate_content_context,
    verify_persistent_carrier,
)
from folioview_shared.encrypted.private_resources import (
    REPORT_PROFILE,
    report_source_request,
    require_report_source_permit,
)
from folioview_shared.encrypted.schema import validate_schema
from folioview_shared.identity import owner_key

from .persistent_agents import PersistentAgentService, stored_identity
from .persistent_execution import PersistentExecutionService, run_path, stored_run
from .preparations import source_versions
from .store import StoreUnavailable, document_path, private_resource_writer_fence_path
from .user_vault_authority import scoped_user_vaults
from .vaults import _current, _selection

PAGE_SIZE = 64


def result_id(owner, vault, run):
    return "presult_" + digest([owner, vault, run])


def result_path(owner, vault, result):
    return document_path("hub_persistent_results", owner, vault, result)


def operation_path(owner, vault, connection, operation):
    return document_path("hub_persistent_result_operations", owner, vault, connection, operation)


def stored_result(unit, owner, vault, result):
    row = unit.get(result_path(owner, vault, result))
    if row is None:
        raise ContractError("not_found")
    try:
        if set(row) - {"taskCenter"} != {"metadata", "context", "fingerprint", "receipt"}:
            raise StoreUnavailable
        c = validate_content_context(row["context"])
        if "taskCenter" in row:
            from .task_center_results import validate_attribution

            validate_attribution(row["taskCenter"], c)
        meta = row["metadata"]
        receipt = row["receipt"]
        validate_schema("Digest", row["fingerprint"])
        if set(meta) != {
            "resultId",
            "taskId",
            "runId",
            "connectionId",
            "receivedAt",
            "stateVersion",
            "read",
            "starred",
            "archived",
        }:
            raise StoreUnavailable
        if (c["ownerSubject"], c["vaultId"], c["objectId"], c["objectType"], c["revision"]) != (
            owner,
            vault,
            result,
            "result_revision",
            1,
        ):
            raise StoreUnavailable
        if (
            result != result_id(owner, vault, c["runId"])
            or any(type(meta[k]) is not bool for k in ("read", "starred", "archived"))
            or type(meta["stateVersion"]) is not int
            or meta["stateVersion"] < 0
        ):
            raise StoreUnavailable
        for k in ("resultId", "taskId", "runId", "connectionId"):
            validate_schema("Identifier", meta[k])
        if (
            any(meta[k] != c[k] for k in ("taskId", "runId", "connectionId"))
            or meta["resultId"] != result
            or type(meta["receivedAt"]) is not int
        ):
            raise StoreUnavailable
        expected = {
            "contractVersion": CONTRACT_VERSION,
            "profile": CONTENT_PROFILE,
            "resultId": result,
            "runId": c["runId"],
            "taskId": c["taskId"],
            "connectionId": c["connectionId"],
            "revision": 1,
            "publicationId": c["stableOperationId"],
            "fingerprint": row["fingerprint"],
            "manifestFingerprint": c["manifestFingerprint"],
            "receivedAt": meta["receivedAt"],
        }
        if receipt != expected:
            raise StoreUnavailable
    except (ContractError, KeyError, TypeError):
        raise StoreUnavailable from None
    return row


def report_source_bindings(manifest):
    return [
        {key: item[key] for key in ("ref", "sourceEpoch", "sourceRevision")}
        for item in manifest["inputs"]
    ]


class _OwnerResultSnapshot:
    """Only selected rows from this read attempt, detached for the original validators."""

    def __init__(self, unit, paths):
        self.rows = unit.get_many(paths)

    def get(self, path):
        if path not in self.rows:
            raise StoreUnavailable
        return copy.deepcopy(self.rows[path])


class PersistentResultService(PersistentExecutionService):
    def __init__(
        self,
        store,
        catalogue,
        *,
        report_source_authority=None,
        selected_report_owner=None,
        **kwargs,
    ):
        super().__init__(store, catalogue, **kwargs)
        self.report_source_authority = report_source_authority
        self.selected_report_owner = selected_report_owner

    def _source_writer(self, unit, owner, vault):
        selected = self.selected_report_owner
        fence = unit.get(private_resource_writer_fence_path(owner))
        if fence is None:
            if selected == owner:
                raise ContractError("source_unavailable")
            return self.report_source_authority if selected is None else None
        if (
            selected != owner
            or self.report_source_authority is None
            or fence.get("ownerSubject") != owner
            or fence.get("vaultId") != vault
            or fence.get("state") != "transferred"
            or type(fence.get("writerEpoch")) is not int
            or fence["writerEpoch"] != 2
        ):
            raise ContractError("source_unavailable")
        return self.report_source_authority

    def _check_result_retry(self, unit, owner, vault, result, carrier):
        """Optional exact-artifact retry check; legacy receipt reads stay unchanged."""

    def result_receipt(self, owner, vault, connection, proof, path, request):
        if type(request) is not dict or set(request) != {"runId"}:
            raise ContractError("malformed_request")
        validate_schema("Identifier", request["runId"])

        user_scope = self._request_user_scope(owner, vault, connection)

        def read(unit):
            self.authenticate(
                unit, owner, vault, connection, proof, path, request, user_scope=user_scope
            )
            run, manifest = stored_run(unit, owner, vault, request["runId"])
            if manifest["connectionId"] != connection or run["resultId"] is None:
                raise ContractError("not_found")
            return stored_result(unit, owner, vault, run["resultId"])["receipt"]

        return self.store.transact(read)

    def _original(self, unit, owner, vault, connection, operation, fingerprint, run, carrier):
        saved = unit.get(operation_path(owner, vault, connection, operation))
        if saved is None:
            return None
        if saved != {
            "runId": run,
            "resultId": result_id(owner, vault, run),
            "fingerprint": fingerprint,
        }:
            raise ContractError("idempotency_conflict")
        row = stored_result(unit, owner, vault, saved["resultId"])
        if row["fingerprint"] != fingerprint or row["context"]["stableOperationId"] != operation:
            raise StoreUnavailable
        self._check_result_retry(unit, owner, vault, saved["resultId"], carrier)
        return row["receipt"]

    def _append(self, unit, owner, vault, result):
        path = document_path("hub_persistent_result_indexes", owner, vault)
        head = unit.get(path)
        if head is not None and (set(head) != {"pageId"} or type(head["pageId"]) is not str):
            raise StoreUnavailable
        page = None if head is None else self._page(unit, owner, vault, head["pageId"])
        if page is None or len(page["resultIds"]) >= PAGE_SIZE:
            ident = "pidx_" + digest([owner, vault, result])
            page = {
                "pageId": ident,
                "previous": None if head is None else head["pageId"],
                "resultIds": [],
            }
            if (
                unit.get(document_path("hub_persistent_result_pages", owner, vault, ident))
                is not None
            ):
                raise StoreUnavailable
        if result in page["resultIds"]:
            raise StoreUnavailable
        page["resultIds"].append(result)
        unit.put(document_path("hub_persistent_result_pages", owner, vault, page["pageId"]), page)
        unit.put(path, {"pageId": page["pageId"]})

    def _page(self, unit, owner, vault, page_id):
        if type(page_id) is not str or re.fullmatch(r"pidx_[a-f0-9]{64}", page_id) is None:
            raise ContractError("malformed_request")
        page = unit.get(document_path("hub_persistent_result_pages", owner, vault, page_id))
        if page is None:
            raise ContractError("not_found")
        if (
            set(page) != {"pageId", "previous", "resultIds"}
            or page["pageId"] != page_id
            or type(page["resultIds"]) is not list
            or not 1 <= len(page["resultIds"]) <= PAGE_SIZE
            or len(set(page["resultIds"])) != len(page["resultIds"])
            or page["previous"] == page_id
        ):
            raise StoreUnavailable
        if page["previous"] is not None and (
            type(page["previous"]) is not str
            or re.fullmatch(r"pidx_[a-f0-9]{64}", page["previous"]) is None
        ):
            raise StoreUnavailable
        if any(
            type(r) is not str or re.fullmatch(r"presult_[a-f0-9]{64}", r) is None
            for r in page["resultIds"]
        ):
            raise StoreUnavailable
        return page

    def submit(self, owner, vault, connection, proof, path, request):
        if type(request) is not dict or set(request) != {"runId", "operationId", "envelope"}:
            raise ContractError("malformed_request")
        validate_schema("Identifier", request["runId"])
        validate_schema("OperationIdentifier", request["operationId"])
        carrier, c = inspect_persistent_carrier(request["envelope"])
        fingerprint = signing_input_fingerprint(carrier["proof"])
        if c["stableOperationId"] != request["operationId"] or c["objectType"] != "result_revision":
            raise ContractError("recipient_binding_mismatch")

        user_scope = self._request_user_scope(owner, vault, connection)

        def existing(unit):
            uid, *_ = self.authenticate(
                unit, owner, vault, connection, proof, path, request, user_scope=user_scope
            )
            prior = self._original(
                unit,
                owner,
                vault,
                connection,
                request["operationId"],
                fingerprint,
                request["runId"],
                carrier,
            )
            if prior is not None:
                return prior, uid, None, None
            authority = self._source_writer(unit, owner, vault)
            if authority is None:
                return None, uid, None, None
            row, manifest = stored_run(unit, owner, vault, request["runId"])
            if (
                manifest["connectionId"] != connection
                or c["ownerSubject"] != owner
                or c["vaultId"] != vault
                or c["connectionId"] != connection
                or c["runId"] != manifest["runId"]
                or c["manifestFingerprint"] != row["manifestFingerprint"]
            ):
                raise ContractError("recipient_binding_mismatch")
            if manifest["resultPolicy"] != "owner_inbox":
                raise ContractError("insufficient_scope")
            if row["state"] != "ready":
                raise ContractError("initial_result_exists")
            return (
                None,
                uid,
                (row["manifestFingerprint"], report_source_bindings(manifest)),
                authority,
            )

        previous, uid, observed, authority = self.store.transact(existing)
        if previous is not None:
            return previous
        sources, requested, decision, check = None, None, None, None
        if observed is None:
            sources = source_versions(self.catalogue, uid)
        else:
            manifest_fingerprint, bindings = observed
            requested = report_source_request(
                {
                    "contractVersion": CONTRACT_VERSION,
                    "profile": REPORT_PROFILE,
                    "purpose": "report_submit",
                    "ownerSubject": owner,
                    "vaultId": vault,
                    "connectionId": connection,
                    "runId": request["runId"],
                    "operationId": request["operationId"],
                    "attemptId": uuid4().hex,
                    "manifestFingerprint": manifest_fingerprint,
                    "reportFingerprint": fingerprint,
                    "resources": bindings,
                }
            )
            decision = authority.decide(uid, requested)
            require_report_source_permit(decision, request=requested, now=self.now())

            def check(row, manifest):
                if (
                    row["manifestFingerprint"] != requested["manifestFingerprint"]
                    or report_source_bindings(manifest) != requested["resources"]
                ):
                    raise ContractError("recipient_binding_mismatch")
                require_report_source_permit(decision, request=requested, now=self.now())
                # User approved each exact revision. The consent verifier only
                # needs that lower bound and keeps checking the local policy.
                return {
                    canonical_json(binding["ref"]): {
                        "sourceEpoch": binding["sourceEpoch"],
                        "revision": binding["sourceRevision"],
                    }
                    for binding in requested["resources"]
                }

        if user_scope is not None:
            user_scope = self.user_vaults.read(uid, vault)

        def write(unit):
            self.authenticate(
                unit, owner, vault, connection, proof, path, request, user_scope=user_scope
            )
            prior = self._original(
                unit,
                owner,
                vault,
                connection,
                request["operationId"],
                fingerprint,
                request["runId"],
                carrier,
            )
            if prior is not None:
                return prior
            if self._source_writer(unit, owner, vault) is not authority:
                raise ContractError("source_unavailable")
            row, m, v, registry, identity = self.current_run(
                unit,
                owner,
                vault,
                connection,
                proof,
                path,
                request,
                request["runId"],
                sources,
                report_source_check=check,
                user_scope=user_scope,
            )
            if m["resultPolicy"] != "owner_inbox":
                raise ContractError("insufficient_scope")
            ident = result_id(owner, vault, m["runId"])
            if row["state"] != "ready" or unit.get(result_path(owner, vault, ident)) is not None:
                raise ContractError("initial_result_exists")
            _, recipients = _selection(registry, self.now())
            verified = verify_persistent_carrier(
                carrier,
                registry=registry,
                root_jwk=v["rootJwk"],
                current_identity=identity,
                expectation=PersistentEnvelopeExpectation(
                    owner,
                    vault,
                    connection,
                    identity["clientId"],
                    "result_revision",
                    ident,
                    1,
                    tuple(recipients),
                    {
                        **{
                            k: m[k]
                            for k in (
                                "taskId",
                                "taskVersion",
                                "executionEpoch",
                                "authorityId",
                                "authorityVersion",
                                "runId",
                            )
                        },
                        "manifestFingerprint": row["manifestFingerprint"],
                    },
                ),
                now=self.now(),
            )
            self.authenticate(
                unit, owner, vault, connection, proof, path, request, user_scope=user_scope
            )
            if _selection(registry, self.now())[1] != recipients:
                raise ContractError("registry_conflict")
            now = self.now()
            receipt = {
                "contractVersion": CONTRACT_VERSION,
                "profile": CONTENT_PROFILE,
                "resultId": ident,
                "runId": m["runId"],
                "taskId": m["taskId"],
                "connectionId": connection,
                "revision": 1,
                "publicationId": request["operationId"],
                "fingerprint": verified.fingerprint,
                "manifestFingerprint": row["manifestFingerprint"],
                "receivedAt": now,
            }
            meta = {
                "resultId": ident,
                "taskId": m["taskId"],
                "runId": m["runId"],
                "connectionId": connection,
                "receivedAt": now,
                "stateVersion": 0,
                "read": False,
                "starred": False,
                "archived": False,
            }
            self._append(unit, owner, vault, ident)
            if "taskCenter" in row:
                from .task_center import observe_center_result
                from .task_center_results import append_result

                append_result(unit, row["taskCenter"], ident)
                observe_center_result(unit, row["taskCenter"], ident)
            self.authenticate(
                unit, owner, vault, connection, proof, path, request, user_scope=user_scope
            )
            if self.now() >= m["expiresAt"] or _selection(registry, self.now())[1] != recipients:
                raise ContractError("key_authorization_required")
            unit.put(
                result_path(owner, vault, ident),
                {
                    **({"taskCenter": row["taskCenter"]} if "taskCenter" in row else {}),
                    "metadata": meta,
                    "context": verified.context,
                    "fingerprint": verified.fingerprint,
                    "receipt": receipt,
                },
            )
            unit.put(
                document_path("hub_persistent_result_content", owner, vault, ident),
                {"carrierJson": canonical_json(verified.carrier).decode()},
            )
            unit.put(
                operation_path(owner, vault, connection, request["operationId"]),
                {"runId": m["runId"], "resultId": ident, "fingerprint": verified.fingerprint},
            )
            from .persistent_plans import observe_execution

            observe_execution(unit, m, result_id=ident, received_at=now)
            row.update(state="submitted", resultId=ident)
            unit.put(run_path(owner, vault, m["runId"]), row)
            if requested is not None:
                require_report_source_permit(decision, request=requested, now=self.now())
            return receipt

        return self.store.transact(write)


def _history_through(history, context):
    """Select the exact issuance checkpoint from an already admitted history."""
    try:
        _, first = _signed_parts(history[0]["checkpoint"])
        sequence = context["registrySequence"]
        index = sequence - first["registrySequence"]
        if not 0 <= index < len(history):
            return None
        _, checkpoint = _signed_parts(history[index]["checkpoint"])
        if (
            checkpoint["registrySequence"] == sequence
            and digest(checkpoint) == context["checkpointDigest"]
        ):
            return history[: index + 1]
    except (ContractError, IndexError, KeyError, TypeError):
        raise StoreUnavailable from None
    return None


class PersistentOwnerResultService:
    """Owner history has no Agent authentication, submit method or OAuth config."""

    def __init__(self, store, *, clock, user_vaults=None):
        self.store, self.clock = store, clock
        self.user_vaults = user_vaults if user_vaults is not None else scoped_user_vaults(store)

    now = PersistentAgentService.now
    _page = PersistentResultService._page

    def owner_get(self, uid, vault, result):
        for value in (vault, result):
            validate_schema("Identifier", value)
        owner = owner_key(uid)

        def read(unit, user_scope=None):
            v, legacy = _current(unit, owner, self.now(), vault)
            row = stored_result(unit, owner, vault, result)
            from .task_lifecycle import require_visible

            require_visible(unit, owner, vault, row["context"]["taskId"])
            run, m = stored_run(unit, owner, vault, row["context"]["runId"])
            if (
                run["ownerUid"] != uid
                or run["resultId"] != result
                or row["context"]["manifestFingerprint"] != run["manifestFingerprint"]
            ):
                raise StoreUnavailable
            blob = unit.get(document_path("hub_persistent_result_content", owner, vault, result))
            if blob is None or set(blob) != {"carrierJson"}:
                raise StoreUnavailable
            carrier, context = inspect_persistent_carrier(
                strict_json_loads(blob["carrierJson"], max_bytes=524288)
            )
            if (
                context != row["context"]
                or signing_input_fingerprint(carrier["proof"]) != row["fingerprint"]
            ):
                raise StoreUnavailable
            identity = stored_identity(
                unit,
                owner,
                vault,
                m["connectionId"],
                binding_fingerprint=run["identity"]["bindingFingerprint"],
            )
            if identity is None:
                raise StoreUnavailable
            if (
                legacy.checkpoint_history.get(context["registrySequence"])
                == context["checkpointDigest"]
            ):
                history = v["registryHistory"]
            else:
                # A transferred Run carries the verified User history seen at
                # creation. A report can also be issued after that history grows.
                history = _history_through(run["registryHistory"], context)
                if history is None and user_scope is not None:
                    user_scope.require_current(unit, self.now())
                    authority = user_scope.authority
                    if authority["rootJwk"] != v["rootJwk"]:
                        raise StoreUnavailable
                    history = _history_through(authority["registryHistory"], context)
                if history is None:
                    return None
            response = {
                "contractVersion": CONTRACT_VERSION,
                "profile": CONTENT_PROFILE,
                "metadata": row["metadata"],
                "receipt": row["receipt"],
                "envelope": carrier,
                "manifest": m,
                "manifestFingerprint": run["manifestFingerprint"],
                "identity": run["identity"],
                "binding": identity["binding"],
                "rootJwk": v["rootJwk"],
                "registryHistory": history,
            }
            check_read_response(response)
            return response

        response = self.store.transact(read)
        if response is not None:
            return response
        user_scope = self.user_vaults.read(uid, vault)
        if user_scope is None:
            raise ContractError("source_unavailable")
        response = self.store.transact(lambda unit: read(unit, user_scope))
        if response is None:
            raise ContractError("source_unavailable")
        return response

    def owner_list(self, uid, vault, *, limit=20, cursor=None):
        validate_schema("Identifier", vault)
        if type(limit) is not int or not 1 <= limit <= 50:
            raise ContractError("malformed_request")
        selected = None
        if cursor is not None:
            if (
                type(cursor) is not str
                or re.fullmatch(r"pidx_[a-f0-9]{64}:[0-9]{1,2}", cursor) is None
            ):
                raise ContractError("unsupported_query")
            ident, offset = cursor.split(":")
            selected = (ident, int(offset))
        owner = owner_key(uid)

        def read(unit):
            _current(unit, owner, self.now(), vault)
            return self._list(unit, owner, vault, limit=limit, selected=selected)

        return self.store.transact(read)

    def _list(self, unit, owner, vault, *, limit, selected):
        if selected is None:
            head = unit.get(document_path("hub_persistent_result_indexes", owner, vault))
            if head is None:
                return {
                    "contractVersion": CONTRACT_VERSION,
                    "profile": CONTENT_PROFILE,
                    "items": [],
                    "nextCursor": None,
                }
            if set(head) != {"pageId"}:
                raise StoreUnavailable
            page = self._page(unit, owner, vault, head["pageId"])
            before = len(page["resultIds"])
        else:
            page = self._page(unit, owner, vault, selected[0])
            before = selected[1]
            if not 0 < before <= len(page["resultIds"]):
                raise ContractError("unsupported_query")
        begin = max(0, before - limit)
        ids = list(reversed(page["resultIds"][begin:before]))
        from .task_lifecycle import lifecycle_path, visible_metadata

        snapshot = _OwnerResultSnapshot(
            unit,
            [result_path(owner, vault, r) for r in ids] + [lifecycle_path(owner, vault)],
        )

        items = visible_metadata(
            snapshot,
            owner,
            vault,
            [stored_result(snapshot, owner, vault, r)["metadata"] for r in ids],
        )
        cursor = f"{page['pageId']}:{begin}" if begin else None
        if not begin and page["previous"] is not None:
            previous = self._page(unit, owner, vault, page["previous"])
            cursor = f"{previous['pageId']}:{len(previous['resultIds'])}"
        return {
            "contractVersion": CONTRACT_VERSION,
            "profile": CONTENT_PROFILE,
            "items": items,
            "nextCursor": cursor,
        }

    def owner_state(self, uid, vault, result, signed, operation, author):
        owner = owner_key(uid)
        validate_schema("OperationIdentifier", operation)
        validate_schema("KeyId", author)
        current = self.user_vaults.read(uid, vault)

        def write(unit):
            now = self.now()
            _, registry = _current(unit, owner, now, vault)
            if current is None:
                if unit.get(private_resource_writer_fence_path(owner)) is not None:
                    raise ContractError("source_unavailable")
            else:
                current.require_current(unit, now)
                if current.cursor.registry.root_key_id != registry.root_key_id:
                    raise ContractError("registry_conflict")
                registry = current.cursor.registry
            row = stored_result(unit, owner, vault, result)
            from .task_lifecycle import require_visible

            require_visible(unit, owner, vault, row["context"]["taskId"])
            header, payload = _signed_parts(signed)
            command = verify_control_command(
                signed,
                registry=registry,
                expected_action="result_state_update",
                expected_target_id=result,
                expected_version=payload.get("expectedVersion"),
                expected_source_epoch=None,
                expected_parameters=payload.get("parameters"),
                now=self.now(),
            )
            if command["stableOperationId"] != operation or header["kid"] != author:
                raise ContractError("recipient_binding_mismatch")
            path = document_path(
                "hub_persistent_result_state_operations", owner, vault, result, operation
            )
            old = unit.get(path)
            fp = signing_input_fingerprint(signed)
            if old is not None:
                if old["fingerprint"] != fp:
                    raise ContractError("idempotency_conflict")
                return old["metadata"]
            if command["expectedVersion"] != row["metadata"]["stateVersion"]:
                raise ContractError("version_conflict")
            if row["metadata"]["stateVersion"] >= 9007199254740991:
                raise ContractError("version_conflict")
            registry.cert(author, role="device_sig", connection_id=None, now=self.now())
            meta = {
                **row["metadata"],
                **command["parameters"],
                "stateVersion": row["metadata"]["stateVersion"] + 1,
            }
            if current is not None:
                current.require_current(unit, self.now())
            unit.put(result_path(owner, vault, result), {**row, "metadata": meta})
            unit.put(path, {"fingerprint": fp, "metadata": meta})
            return meta

        return self.store.transact(write)
