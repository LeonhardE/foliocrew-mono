"""Compound discovery retains real authority, final aliases and bounded SDK reads."""

import copy
import unittest
from contextlib import closing
from unittest.mock import patch

import test_private_display_name_store as name_fixture
from fixtures import BOOT, OTHER_UID, SOURCE, UID
from google.auth.credentials import AnonymousCredentials
from google.cloud import firestore
from test_firestore_store import MemoryRpc

from app import vaults as vault_module
from app.catalogue import CatalogueService, item
from app.fences import FenceService
from app.private_display_names import (
    PrivateDisplayNameService,
    display_name_capabilities,
    name_path,
)
from app.resource_display import PROFILE, ResourceDisplayService, _response_body
from app.store import FirestoreHubStore, StoreUnavailable, document_path
from app.vaults import VaultService
from folioview_shared.encrypted import budgets
from folioview_shared.encrypted.constants import CONTRACT_VERSION
from folioview_shared.encrypted.crypto import _signed_parts
from folioview_shared.encrypted.errors import ContractError
from folioview_shared.encrypted.jsonutil import canonical_json
from folioview_shared.encrypted.private_display_names import decrypt_display_name


class Sources:
    def __init__(self, callback=None, *, unavailable=False):
        self.time, self.calls = 100.0, 0
        self.callback, self.unavailable = callback, unavailable

    def clock(self):
        return self.time

    def discover(self, uid, sources, *, deadline):
        self.calls += 1
        if self.callback:
            self.callback()
        return {
            "portfolio": [
                item(
                    s["ref"],
                    state="unavailable" if self.unavailable else s["fence"]["state"],
                    revision=None if self.unavailable else 0,
                    epoch=s["fence"]["sourceEpoch"],
                    evidence="not_prepared",
                )
                for s in sources
            ],
            "user": {
                kind: item(None, state="uninitialized", evidence="not_prepared")
                for kind in ("watchlist", "channel_follows")
            },
        }


class ResourceDisplayTests(unittest.TestCase):
    def setUp(self):
        self.fixture = name_fixture.DisplayNameStoreTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.f = self.fixture.f
        self.sqlite = self.fixture.store
        self.client = firestore.Client(
            project="synthetic-hub", database="agent-hub", credentials=AnonymousCredentials()
        )
        self.addCleanup(self.client.close)
        self.rpc = MemoryRpc(self.client)
        self.client._firestore_api_internal = self.rpc
        self.firestore = FirestoreHubStore("synthetic-hub", "agent-hub", client=self.client)
        vaults = self.vaults(self.firestore)
        vaults.bootstrap(UID, self.f.bootstrap(), BOOT)
        response = vaults.create_source(
            UID,
            self.f.vault,
            SOURCE,
            self.f.control(),
            "synthetic_source_create_0001",
            self.f.kid("device_sig"),
        )
        self.assertEqual(self.fixture.ref, response["source"]["resourceRef"])
        self.stores = (self.sqlite, self.firestore)

    def vaults(self, store):
        return VaultService(store, clock=lambda: self.fixture.now)

    def names(self, store):
        return PrivateDisplayNameService(store, clock=lambda: self.fixture.now)

    def service(self, store, sources=None):
        return ResourceDisplayService(self.vaults(store), sources or Sources())

    def snapshot(self, store):
        if store is self.sqlite:
            with closing(store.connect()) as connection:
                return connection.execute(
                    "SELECT path,body FROM hub_documents ORDER BY path"
                ).fetchall()
        return copy.deepcopy(self.rpc.documents)

    def replace(self, store, path, value):
        store.transact(lambda unit: unit.put(path, value))

    def test_full_has_exact_original_components_scope_and_no_read_writes(self):
        for store in self.stores:
            with self.subTest(backend=type(store).__name__):
                self.names(store).write(UID, self.f.vault, SOURCE, *self.fixture.packet())
                before = self.snapshot(store)
                result = self.service(store).read(UID)
                self.assertEqual(
                    set(result),
                    {
                        "contractVersion",
                        "profile",
                        "mode",
                        "scope",
                        "catalogue",
                        "displayNameCapabilities",
                        "displayNames",
                    },
                )
                self.assertEqual((result["profile"], result["mode"]), (PROFILE, "full"))
                self.assertEqual(
                    result["catalogue"], CatalogueService(self.vaults(store), Sources()).read(UID)
                )
                self.assertEqual(result["displayNameCapabilities"], display_name_capabilities())
                self.assertEqual(
                    result["displayNames"], self.names(store).listing(UID, self.f.vault)
                )
                self.assertEqual(
                    result["scope"],
                    {
                        "ownerSubject": self.f.owner,
                        "vaultId": self.f.vault,
                        "rootKeyId": self.f.root_id,
                        "version": 2,
                        "registrySequence": 1,
                        "checkpointDigest": self.f.registry.checkpoint_digest,
                        "keyEpoch": 1,
                    },
                )
                self.assertLess(len(canonical_json(result)), 1_048_576)
                self.assertEqual(before, self.snapshot(store))

    def test_static_signature_memo_is_private_to_each_read_but_final_row_is_verified_again(self):
        for store in self.stores:
            with (
                self.subTest(backend=type(store).__name__),
                patch.object(
                    vault_module, "verify_registry", wraps=vault_module.verify_registry
                ) as verify,
            ):
                self.service(store).read(UID)
                self.assertEqual(verify.call_count, 1)
                self.service(store).read(UID)
                self.assertEqual(verify.call_count, 2)

    def test_actual_sdk_two_transactions_three_get_legs_and_max21_documents(self):
        created = 1
        for count in (1, 2, 10):
            with self.subTest(sources=count):
                for index in range(created, count):
                    source, op = f"source_{index}", f"synthetic_compound_source_{index:04d}"
                    self.vaults(self.firestore).create_source(
                        UID,
                        self.f.vault,
                        source,
                        self.f.control(source, op),
                        op,
                        self.f.kid("device_sig"),
                    )
                created = count
                # Keep this original cold-path counter independent of earlier
                # subtests. Warm path hints have their own exact SDK regression.
                self.firestore._catalogue_fence_keys.discard(self.f.owner)
                self.rpc.calls.clear()
                self.service(self.firestore).read(UID)
                gets = [args for kind, args in self.rpc.calls if kind == "get"]
                self.assertEqual(
                    [len(x["request"]["documents"]) for x in gets], [1, count, 1 + 2 * count]
                )
                self.assertEqual(sum(kind == "begin" for kind, _ in self.rpc.calls), 0)
                self.assertEqual(sum(kind == "commit" for kind, _ in self.rpc.calls), 2)
                self.assertTrue(
                    all(
                        not x["request"]["writes"] for kind, x in self.rpc.calls if kind == "commit"
                    )
                )
                self.assertTrue(
                    all(
                        x["request"].get("transaction")
                        or x["request"]["new_transaction"]._pb.WhichOneof("mode") == "read_write"
                        for x in gets
                    )
                )

    def test_active_vault_without_registered_sources_is_full_and_does_not_invent_aliases(self):
        path = document_path("hub_vaults", self.f.owner)
        for store in self.stores:
            row = store.transact(lambda unit: unit.get(path))
            row.update(sources=[], version=1, operationCount=1)
            self.replace(store, path, row)
            response = self.service(store).read(UID)
            self.assertEqual(response["mode"], "full")
            self.assertEqual(response["scope"]["version"], 1)
            self.assertEqual(response["catalogue"]["groups"][0]["status"], "uninitialized")
            self.assertEqual(response["displayNames"]["items"], [])

    def test_rename_during_remote_phase_is_from_final_snapshot_without_transaction_or_plaintext(
        self,
    ):
        for store in self.stores:
            with self.subTest(backend=type(store).__name__):
                names = self.names(store)
                initial = names.write(UID, self.f.vault, SOURCE, *self.fixture.packet())
                saved = []
                transaction_active = [False]
                original = store.transact

                def transact(callback, transaction_active=transaction_active, original=original):
                    def run(unit):
                        self.assertFalse(transaction_active[0])
                        transaction_active[0] = True
                        try:
                            return callback(unit)
                        finally:
                            transaction_active[0] = False

                    return original(run)

                def rename(
                    transaction_active=transaction_active, saved=saved, names=names, initial=initial
                ):
                    self.assertFalse(
                        transaction_active[0], "external discovery cannot hold a DB transaction"
                    )
                    saved.append(
                        names.write(
                            UID,
                            self.f.vault,
                            SOURCE,
                            *self.fixture.packet(
                                state=initial["item"]["state"], name="Synthetic renamed account"
                            ),
                        )
                    )

                with patch.object(store, "transact", side_effect=transact):
                    response = self.service(store, Sources(rename)).read(UID)
                self.assertEqual(response["displayNames"]["items"], [saved[0]["item"]])
                self.assertNotIn("Synthetic renamed account", canonical_json(response).decode())
                _, p = _signed_parts(saved[0]["item"]["command"])
                self.assertEqual(
                    decrypt_display_name(p["envelope"], self.f.keys["recovery_enc"], context=p),
                    "Synthetic renamed account",
                )

    def test_first_fence_or_delete_during_remote_phase_rejects_whole_response_at_same_vault_version(
        self,
    ):
        for store in self.stores:
            for reason in ("account_scope_changed", "deleted"):
                with self.subTest(backend=type(store).__name__, reason=reason):
                    # Each loop intentionally preserves the Vault version while
                    # advancing the full existing source fence independently.
                    old = CatalogueService(self.vaults(store), Sources()).context(UID)
                    epoch = old["sources"][0]["fence"]["sourceEpoch"]
                    operation = f"synthetic_fence_{reason}_{epoch}"

                    def change(store=store, reason=reason, epoch=epoch, operation=operation):
                        FenceService(store, clock=lambda: 1000).invalidate(
                            {
                                "contractVersion": CONTRACT_VERSION,
                                "ownerSubject": self.f.owner,
                                "mutationId": operation,
                                "ref": self.fixture.ref,
                                "expectedSourceEpoch": epoch,
                                "newSourceEpoch": epoch + 1,
                                "reason": reason,
                            },
                            source_service="portfolio",
                        )

                    with self.assertRaises(ContractError) as failed:
                        self.service(store, Sources(change)).read(UID)
                    self.assertEqual(failed.exception.code, "version_conflict")

    def test_new_source_or_registry_during_remote_phase_cannot_reuse_old_scope(self):
        for store in self.stores:

            def source_change(store=store):
                name, op = "source_new", "synthetic_compound_new_source_01"
                self.vaults(store).create_source(
                    UID, self.f.vault, name, self.f.control(name, op), op, self.f.kid("device_sig")
                )

            with (
                self.subTest(backend=type(store).__name__, change="source"),
                self.assertRaises(ContractError) as failed,
            ):
                self.service(store, Sources(source_change)).read(UID)
            self.assertEqual(failed.exception.code, "version_conflict")

            def registry_change(store=store):
                version = store.transact(
                    lambda unit: unit.get(document_path("hub_vaults", self.f.owner))
                )["version"]
                self.vaults(store).update_registry(
                    UID,
                    self.f.vault,
                    {
                        "contractVersion": CONTRACT_VERSION,
                        "expectedVersion": version,
                        "registryBundle": self.f.make_bundle(previous=self.f.registry),
                    },
                    "synthetic_compound_registry_01",
                )

            with (
                self.subTest(backend=type(store).__name__, change="registry"),
                self.assertRaises(ContractError) as failed,
            ):
                self.service(store, Sources(registry_change)).read(UID)
            self.assertEqual(failed.exception.code, "version_conflict")

    def test_same_version_changed_incarnation_or_root_and_missing_final_vault_fail_closed(self):
        path = document_path("hub_vaults", self.f.owner)
        for store in self.stores:
            original = store.transact(lambda unit: unit.get(path))
            for kind in ("incarnation", "root", "archive_field", "missing"):
                self.replace(store, path, original)

                def change(store=store, kind=kind, original=original):
                    value = copy.deepcopy(original)
                    if kind == "incarnation":
                        value["sources"][0]["resourceRef"]["incarnation"] = "foreign_incarnation"
                    elif kind == "root":
                        value["rootKeyId"] = "A" * 43
                    elif kind == "archive_field":
                        value.pop("archive")
                    else:
                        if store is self.sqlite:
                            with closing(store.connect()) as connection:
                                connection.execute(
                                    "DELETE FROM hub_documents WHERE path=?", (path,)
                                )
                        else:
                            self.rpc.documents.pop(self.client.document(path)._document_path)
                        return
                    self.replace(store, path, value)

                with (
                    self.subTest(backend=type(store).__name__, kind=kind),
                    self.assertRaises((ContractError, StoreUnavailable)) as failed,
                ):
                    self.service(store, Sources(change)).read(UID)
                if kind == "archive_field":
                    self.assertIsInstance(failed.exception, StoreUnavailable)

    def test_malformed_alias_or_missing_batch_member_is_not_separate_or_empty(self):
        alias = name_path(self.f.owner, self.f.vault, self.f.root_id, self.fixture.ref)
        for store in self.stores:
            self.replace(store, alias, {"state": {}, "command": {}, "unexpected": True})
            with self.subTest(backend=type(store).__name__), self.assertRaises(StoreUnavailable):
                self.service(store).read(UID)
        # A malformed SDK response cannot masquerade as confirmed alias absence.
        self.rpc.documents.pop(self.client.document(alias)._document_path)
        original = self.rpc.batch_get_documents
        alias_name = self.client.document(alias)._document_path

        def missing(**kwargs):
            rows = list(original(**kwargs))
            return iter(row for row in rows if (row.found.name or row.missing) != alias_name)

        with (
            patch.object(self.rpc, "batch_get_documents", missing),
            self.assertRaises(StoreUnavailable),
        ):
            self.service(self.firestore).read(UID)

    def test_archive_removed_during_discovery_refuses_without_extra_lifecycle_reads(self):
        path = document_path("hub_vaults", self.f.owner)
        for store in self.stores:

            def remove(store=store):
                row = store.transact(lambda unit: unit.get(path))
                row["archive"] = None
                self.replace(store, path, row)
                self.rpc.calls.clear()

            with (
                self.subTest(backend=type(store).__name__),
                self.assertRaises(ContractError) as failed,
            ):
                self.service(store, Sources(remove)).read(UID)
            self.assertEqual(failed.exception.code, "not_found")
            if store is self.firestore:
                gets = [args for kind, args in self.rpc.calls if kind == "get"]
                self.assertEqual([len(args["request"]["documents"]) for args in gets], [3])

    def test_final_sdk_retry_and_sqlite_wait_recheck_current_clock(self):
        def abort():
            self.rpc.aborts = 1
            self.rpc.before_abort = lambda: setattr(
                self.fixture, "now", self.f.registry.issued_at - 1
            )

        with self.assertRaises(ContractError) as failed:
            self.service(self.firestore, Sources(abort)).read(UID)
        self.assertEqual(failed.exception.code, "registry_conflict")
        self.fixture.now = 1000
        original = self.sqlite.transact
        calls = [0]

        def delayed(callback):
            calls[0] += 1
            if calls[0] == 2:
                self.fixture.now = self.f.registry.issued_at - 1
            return original(callback)

        with (
            patch.object(self.sqlite, "transact", side_effect=delayed),
            self.assertRaises(ContractError) as failed,
        ):
            self.service(self.sqlite).read(UID)
        self.assertEqual(failed.exception.code, "registry_conflict")

    def test_deadline_after_remote_read_cannot_return_even_small_success(self):
        for store in self.stores:
            sources = Sources()
            sources.callback = lambda sources=sources: setattr(sources, "time", 111)
            with (
                self.subTest(backend=type(store).__name__),
                self.assertRaises(ContractError) as failed,
            ):
                self.service(store, sources).read(UID)
            self.assertEqual(failed.exception.code, "source_unavailable")

    def test_original_unavailable_groups_remain_truthful_and_do_not_hide_aliases(self):
        for store in self.stores:
            result = self.service(store, Sources(unavailable=True)).read(UID)
            self.assertEqual(result["mode"], "full")
            self.assertEqual(result["catalogue"]["groups"][0]["status"], "unavailable")
            self.assertEqual(result["displayNames"]["items"], [])

    def test_other_owner_and_no_vault_do_not_discover_or_change_old_catalogue(self):
        for store in self.stores:
            sources = Sources()
            with (
                self.subTest(backend=type(store).__name__),
                self.assertRaises(ContractError) as failed,
            ):
                self.service(store, sources).read(OTHER_UID)
            self.assertEqual(failed.exception.code, "not_found")
            self.assertEqual(sources.calls, 0)
            self.assertEqual(
                CatalogueService(self.vaults(store), sources).read(OTHER_UID)["groups"][0][
                    "status"
                ],
                "uninitialized",
            )
            self.assertTrue(display_name_capabilities()["enabled"])

    def test_exact_aggregate_budget_has_only_explicit_small_separate_fallback(self):
        result = self.service(self.sqlite).read(UID)
        exact = len(canonical_json(result))
        args = [
            result[k] for k in ("scope", "catalogue", "displayNameCapabilities", "displayNames")
        ]
        # Tighten the real helper's fixed ceiling solely within this test. Every
        # genuine component still fits; no production limit or API is added.
        with patch.object(budgets, "MAX_READ_BYTES", exact):
            self.assertEqual(_response_body(*args), result)
        with patch.object(budgets, "MAX_READ_BYTES", exact - 1):
            self.assertEqual(
                _response_body(*args),
                {
                    "contractVersion": CONTRACT_VERSION,
                    "profile": PROFILE,
                    "mode": "separate",
                    "reason": "aggregate_too_large",
                },
            )
        with self.assertRaises(ContractError):
            _response_body(result["scope"], {"oversized": "x" * 1_048_576}, *args[2:])


if __name__ == "__main__":
    unittest.main()
