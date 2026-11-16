/** Public alias DTO shape only; signatures and plaintext stay in the original Worker. */
import {
  exact as fields,
  object as record,
  identifier as id,
  TASK_CONTRACT as CONTRACT,
} from "./task-types";
const OP = "[A-Za-z0-9_-]{22,128}";
const integer = (v: unknown, min: number) => Number.isSafeInteger(v) && Number(v) >= min;
const signedObject = (v: unknown) =>
  fields(v, ["protected", "payload", "signature"]) &&
  Object.values(v).every((x) => typeof x === "string" && /^[A-Za-z0-9_-]+$/.test(x));
export function displayNameResponse(path: string, value: unknown, operation?: string) {
  if (!record(value)) return false;
  const profile = "folioview.private-display-name.v1";
  if (value.contractVersion !== CONTRACT || value.profile !== profile) return false;
  if (path.endsWith("/capabilities"))
    return (
      fields(value, ["contractVersion", "profile", "enabled", "maxSources", "maxNameLength"]) &&
      value.enabled === true &&
      value.maxSources === 10 &&
      value.maxNameLength === 80
    );
  const parts = path.split("/");
  const item = (v: unknown) => {
    if (
      !record(v) ||
      !fields(v, ["state", "command"]) ||
      !record(v.state) ||
      !signedObject(v.command) ||
      new TextEncoder().encode(JSON.stringify(v.command)).byteLength > 12288
    )
      return false;
    const s = v.state;
    return (
      fields(s, [
        "contractVersion",
        "profile",
        "ownerSubject",
        "vaultId",
        "rootKeyId",
        "ref",
        "revision",
        "stableOperationId",
        "operationFingerprint",
        "recipientKeyId",
        "acceptedAt",
      ]) &&
      s.contractVersion === CONTRACT &&
      s.profile === profile &&
      [s.ownerSubject, s.vaultId].every(id) &&
      [s.rootKeyId, s.recipientKeyId].every(
        (k) => typeof k === "string" && /^[A-Za-z0-9_-]{43}$/.test(k),
      ) &&
      s.vaultId === parts[4] &&
      record(s.ref) &&
      fields(s.ref, ["kind", "sourceService", "resourceId", "incarnation"]) &&
      s.ref.kind === "holdings" &&
      s.ref.sourceService === "portfolio" &&
      [s.ref.resourceId, s.ref.incarnation].every(id) &&
      (!parts[6] || s.ref.resourceId === parts[6]) &&
      integer(s.revision, 1) &&
      integer(s.acceptedAt, 0) &&
      typeof s.operationFingerprint === "string" &&
      /^[a-f0-9]{64}$/.test(s.operationFingerprint) &&
      typeof s.stableOperationId === "string" &&
      new RegExp(`^${OP}$`).test(s.stableOperationId) &&
      (!parts[8] || s.stableOperationId === parts[8]) &&
      (!operation || s.stableOperationId === operation)
    );
  };
  if (path.endsWith("/holdings"))
    return (
      fields(value, ["contractVersion", "profile", "items"]) &&
      Array.isArray(value.items) &&
      value.items.length <= 10 &&
      value.items.every(item) &&
      new Set(value.items.map((v: any) => v.state.ref.resourceId)).size === value.items.length
    );
  return (
    fields(value, ["contractVersion", "profile", "item"]) &&
    (value.item === null ? !operation && !parts[8] : item(value.item))
  );
}
