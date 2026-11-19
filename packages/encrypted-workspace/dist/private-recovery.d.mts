import type { PublicJson } from "./core.mjs";

/** Verify nonce-bound evidence from the authenticated Owner transport using a local Root pin. */
export function verifyOwnerRecoveryEvidence(
  evidence: unknown,
  options: { request: unknown; pinnedRootKeyId: string; now: number; previous?: unknown },
): Promise<PublicJson>;
