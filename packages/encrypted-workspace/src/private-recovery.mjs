/** Authenticate fresh recovery evidence using caller-trusted transport and a local Root pin. */
import { canonical, deny, digest, integer, parsed, same, validate } from "../dist/core.mjs";
import validators from "./private-recovery-validators.cjs";

const MAX_CONTEXT_BYTES = 16_384;
const RECOVERY_SECONDS = 60;
const CLOCKS = ["registryEpoch", "registrySequence", "keyEpoch"];

function snapshot(schema, value) {
  if (!validators[schema](value)) deny("invalid_schema");
  const bytes = canonical(value);
  if (bytes.length > MAX_CONTEXT_BYTES) deny("payload_too_large");
  return parsed(bytes, true);
}

export async function verifyOwnerRecoveryEvidence(
  evidence,
  { request, pinnedRootKeyId, now, previous = null },
) {
  integer(now);
  validate("KeyId", pinnedRootKeyId);
  const expected = snapshot("PrivateRecoveryRequest", request);
  if (evidence == null) deny("authorization_unavailable");
  const result = snapshot("PrivateRecoveryEvidence", evidence);
  const baseline = previous === null ? null : snapshot("PrivateRecoveryEvidence", previous);
  if (result.ownerSubject !== expected.ownerSubject || result.vaultId !== expected.vaultId)
    deny("recipient_binding_mismatch");
  if (result.rootKeyId !== pinnedRootKeyId) deny("untrusted_key");
  if (result.requestDigest !== (await digest(expected))) deny("recipient_binding_mismatch");
  if (
    result.verifiedAt > now ||
    result.expiresAt <= now ||
    result.expiresAt - result.verifiedAt > RECOVERY_SECONDS
  )
    deny("authorization_unavailable");
  if (result.archive.state !== "active" || result.device !== "active")
    deny("key_authorization_required");

  const current = result.registry;
  const start = result.registryStart;
  if (
    (current.registryEpoch === 1) !== (start === null) ||
    (start !== null &&
      (current.registryEpoch !== start.registryEpoch ||
        current.registrySequence < start.registrySequence ||
        current.keyEpoch < start.keyEpoch ||
        (current.registrySequence === start.registrySequence && !same(current, start))))
  )
    deny("registry_conflict");

  if (baseline !== null) {
    if (["ownerSubject", "vaultId", "rootKeyId"].some((key) => baseline[key] !== result[key]))
      deny("recipient_binding_mismatch");
    const prior = baseline.registry;
    if (
      result.vaultVersion < baseline.vaultVersion ||
      result.archive.version < baseline.archive.version ||
      CLOCKS.some((clock) => current[clock] < prior[clock]) ||
      (current.registrySequence === prior.registrySequence && !same(current, prior)) ||
      (current.registryEpoch === prior.registryEpoch && !same(start, baseline.registryStart))
    )
      deny("rollback_detected");
  }
  return result;
}
