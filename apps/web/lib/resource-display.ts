/** Owner display correlation only. Every alias still passes its original Worker verifier. */
import { exact, identifier, TASK_CONTRACT } from "./task-types";
import { readResourceCatalogue, type ResourceCatalogue } from "./resource-library";
import { displayNameResponse } from "./display-name-contract";
import type { Source, Vault } from "./encrypted-types";
type J = Record<string, any>;
export const RESOURCE_DISPLAY_PATH = "/api/v3/resources/display";
const PROFILE = "folioview.owner-resource-display.v1";
const FIELDS = [
  "ownerSubject",
  "vaultId",
  "rootKeyId",
  "version",
  "registrySequence",
  "checkpointDigest",
  "keyEpoch",
];
export type ResourceDisplayScope = {
  ownerSubject: string;
  vaultId: string;
  rootKeyId: string;
  version: number;
  registrySequence: number;
  checkpointDigest: string;
  keyEpoch: number;
};
const hex = (v: unknown) => typeof v === "string" && /^[a-f0-9]{64}$/.test(v);
const positive = (v: unknown) => Number.isSafeInteger(v) && Number(v) > 0;
const keyId = (v: unknown) => typeof v === "string" && /^[A-Za-z0-9_-]{43}$/.test(v);
const validScope = (v: unknown): v is ResourceDisplayScope =>
  exact(v, FIELDS) &&
  hex(v.ownerSubject) &&
  identifier(v.vaultId) &&
  keyId(v.rootKeyId) &&
  positive(v.version) &&
  positive(v.registrySequence) &&
  v.registrySequence <= 32 &&
  hex(v.checkpointDigest) &&
  positive(v.keyEpoch);
export type ResourceDisplay =
  | { mode: "separate" }
  | {
      mode: "full";
      scope: ResourceDisplayScope;
      catalogue: ResourceCatalogue;
      displayNameCapabilities: J;
      displayNames: { items: J[] };
    };
export function readResourceDisplay(
  value: unknown,
  expected?: ResourceDisplayScope,
): ResourceDisplay {
  const fail = (): never => {
    throw Error("invalid_response");
  };
  if (
    !exact(
      value,
      value && (value as J).mode === "separate"
        ? ["contractVersion", "profile", "mode", "reason"]
        : [
            "contractVersion",
            "profile",
            "mode",
            "scope",
            "catalogue",
            "displayNameCapabilities",
            "displayNames",
          ],
    ) ||
    value.contractVersion !== TASK_CONTRACT ||
    value.profile !== PROFILE ||
    new TextEncoder().encode(JSON.stringify(value)).byteLength > 1048576
  )
    return fail();
  if (value.mode === "separate") {
    if (value.reason !== "aggregate_too_large") return fail();
    return { mode: "separate" };
  }
  if (
    value.mode !== "full" ||
    !validScope(value.scope) ||
    (expected &&
      FIELDS.some((k) => value.scope[k] !== expected[k as keyof ResourceDisplayScope])) ||
    !displayNameResponse(
      "/api/v3/private-display-names/capabilities",
      value.displayNameCapabilities,
    ) ||
    !displayNameResponse(
      `/api/v3/private-display-names/${value.scope.vaultId}/holdings`,
      value.displayNames,
    )
  )
    return fail();
  if (
    [value.displayNameCapabilities, value.displayNames].some(
      (v) => new TextEncoder().encode(JSON.stringify(v)).byteLength > 262144,
    )
  )
    return fail();
  for (const item of value.displayNames.items) {
    if (
      item.state.ownerSubject !== value.scope.ownerSubject ||
      item.state.rootKeyId !== value.scope.rootKeyId
    )
      return fail();
  }
  const catalogue = readResourceCatalogue(value.catalogue);
  return {
    mode: "full",
    scope: value.scope,
    catalogue,
    displayNameCapabilities: value.displayNameCapabilities,
    displayNames: value.displayNames,
  };
}
export type ResourceDisplayContext = {
  readonly coalesceScope: string;
  assertCurrent(): void;
  read(value: unknown): ResourceDisplay;
};
export type ResourceDisplayAccess = {
  readKey: string | null;
  prepare(): ResourceDisplayContext | null;
};
type Current = {
  owner: string | null;
  uid: string | null;
  generation: number;
  session: object | null;
  eligible: boolean;
  vault: Vault | null;
  sources: Source[];
  proof: VerifiedDisplayVault | null;
};
export type VerifiedDisplayVault = {
  readonly key: string;
  valid(current: Current): boolean;
  context(current: () => Current): ResourceDisplayContext | null;
};
const sourceBindings = (rows: Source[]) =>
  rows.map((row) => {
    if (
      !exact(row, ["resourceRef", "sourceEpoch"]) ||
      !exact(row.resourceRef, ["kind", "sourceService", "resourceId", "incarnation"]) ||
      row.resourceRef.kind !== "holdings" ||
      row.resourceRef.sourceService !== "portfolio" ||
      !identifier(row.resourceRef.resourceId) ||
      !identifier(row.resourceRef.incarnation) ||
      !positive(row.sourceEpoch)
    )
      throw Error("invalid_response");
    return [
      row.resourceRef.kind,
      row.resourceRef.sourceService,
      row.resourceRef.resourceId,
      row.resourceRef.incarnation,
      row.sourceEpoch,
    ];
  });
const sha = async (value: Uint8Array) =>
  [...new Uint8Array(await crypto.subtle.digest("SHA-256", value as BufferSource))]
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
/** A failed optional snapshot must leave the original operation available. */
export type ResourceDisplaySnapshot = { readonly vault: Vault; readonly originalRaw: string };
export function resourceDisplaySnapshot(vault: Vault): ResourceDisplaySnapshot | null {
  try {
    const snapshot = structuredClone(vault);
    return Object.freeze({ vault: snapshot, originalRaw: JSON.stringify(snapshot) });
  } catch {
    return null;
  }
}
/** Call only after the original Worker accepted this exact, private RPC snapshot. */
export async function verifiedDisplayVault(
  snapshot: ResourceDisplaySnapshot,
  sources: Source[],
  owner: string,
  uid: string,
  generation: number,
  session: object,
): Promise<VerifiedDisplayVault | null> {
  try {
    const vault = snapshot.vault,
      raw = snapshot.originalRaw;
    if (JSON.stringify(vault) !== raw) return null;
    const privateVault = structuredClone(vault),
      refs = structuredClone(sources);
    const bindings = sourceBindings(refs);
    const refsRaw = JSON.stringify(bindings);
    if (
      !Number.isSafeInteger(generation) ||
      generation < 0 ||
      !owner ||
      !uid ||
      uid.length > 128 ||
      !identifier(privateVault.vaultId) ||
      !keyId(privateVault.rootKeyId) ||
      !positive(privateVault.version) ||
      !Array.isArray(privateVault.registryHistory) ||
      privateVault.registryHistory.length < 1 ||
      privateVault.registryHistory.length > 32 ||
      refs.length > 10 ||
      !privateVault.archive
    )
      return null;
    const payload = privateVault.registryHistory.at(-1)!.checkpoint.payload;
    // The original Worker already verified canonical JSON and the Root signature.
    // Extract correlation fields; do not import a second canonicalizer or verifier.
    if (typeof payload !== "string" || !/^[A-Za-z0-9_-]+$/.test(payload) || payload.length > 174763)
      return null;
    const binary = atob(payload.replace(/-/g, "+").replace(/_/g, "/"));
    if (btoa(binary).replace(/=/g, "").replace(/\+/g, "-").replace(/\//g, "_") !== payload)
      return null;
    const bytes = Uint8Array.from(binary, (c) => c.charCodeAt(0));
    const checkpoint: J = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes));
    const [ownerSubject, checkpointDigest] = await Promise.all([
      sha(new TextEncoder().encode(uid)),
      sha(bytes),
    ]);
    if (JSON.stringify(vault) !== raw) return null;
    const expected: ResourceDisplayScope = {
      ownerSubject,
      vaultId: privateVault.vaultId,
      rootKeyId: privateVault.rootKeyId,
      version: privateVault.version,
      registrySequence: checkpoint.registrySequence,
      checkpointDigest,
      keyEpoch: checkpoint.keyEpoch,
    };
    if (
      !validScope(expected) ||
      checkpoint.contractVersion !== TASK_CONTRACT ||
      checkpoint.artifactType !== "registry_checkpoint" ||
      checkpoint.ownerSubject !== ownerSubject ||
      privateVault.archive.ownerSubject !== ownerSubject ||
      checkpoint.vaultId !== expected.vaultId ||
      checkpoint.rootKeyId !== expected.rootKeyId ||
      checkpoint.rootEpoch !== 1 ||
      checkpoint.registrySequence !== privateVault.registryHistory.length
    )
      return null;
    const coalesceScope = JSON.stringify([expected, generation, bindings]);
    if (new TextEncoder().encode(coalesceScope).byteLength > 8192) return null;
    const matches = (now: Current) => {
      try {
        return (
          now.eligible &&
          now.owner === owner &&
          now.uid === uid &&
          now.generation === generation &&
          now.session === session &&
          now.vault === vault &&
          JSON.stringify(now.vault) === raw &&
          JSON.stringify(sourceBindings(now.sources)) === refsRaw
        );
      } catch {
        return false;
      }
    };
    return {
      key: coalesceScope,
      valid: matches,
      context(current) {
        const sameCurrent = () => {
          const now = current();
          return now.proof?.key === coalesceScope && now.proof.valid(now);
        };
        if (!sameCurrent()) return null;
        const assertCurrent = () => {
          if (!sameCurrent()) throw Error("cancelled");
        };
        return {
          coalesceScope,
          assertCurrent,
          read(value) {
            assertCurrent();
            const result = readResourceDisplay(value, expected);
            if (
              result.mode === "full" &&
              result.displayNames.items.some(
                (item) =>
                  !refs.some((r) =>
                    ["kind", "sourceService", "resourceId", "incarnation"].every(
                      (key) =>
                        r.resourceRef[key as keyof Source["resourceRef"]] === item.state.ref[key],
                    ),
                  ),
              )
            )
              throw Error("invalid_response");
            assertCurrent();
            return result;
          },
        };
      },
    };
  } catch {
    return null;
  }
}
