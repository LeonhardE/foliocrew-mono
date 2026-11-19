import type { PersistentConnectionView } from "./persistent-experience-controller";
type J = Record<string, any>;
/** Presentation only. A slot is never fabricated and history never grants access. */
export function providerGroups(
  views: PersistentConnectionView[],
  states: Record<string, J>,
  now: number,
) {
  return ["muse", "chatgpt"].map((provider) => {
    const rows = views.filter((v) => v.connection.provider === provider),
      state = states[provider],
      slot = state?.slot;
    const active = rows.filter((v) => v.connection.status === "active");
    const revoked = new Set(
      rows.filter((v) => v.connection.status === "revoked").map((v) => v.connection.connectionId),
    );
    const live = active.filter(
      (v) =>
        ["active", "expiring"].includes(v.credential?.status ?? "") &&
        v.credential!.expiresAt > now,
    );
    const reference = slot?.currentCredential;
    const ref = reference && !revoked.has(reference.connectionId) ? reference : null;
    const current = slot
      ? ref
        ? (active.find((v) => {
            const r = v.credential?.reference;
            return (
              r &&
              ["connectionId", "clientId", "credentialGeneration", "credentialFingerprint"].every(
                (k) => r[k] === ref[k],
              )
            );
          }) ?? null)
        : null
      : live.length === 1
        ? live[0]
        : active.length === 1
          ? active[0]
          : null;
    const reviewRequired = Boolean(
      state?.legacyBlockers?.some((id: string) => !revoked.has(id)) ||
      current?.error ||
      (!current && active.some((v) => v.error)) ||
      (!slot && live.length > 1) ||
      (ref && !current),
    );
    const history = active.filter((v) => v !== current);
    return { provider, current, history, reviewRequired };
  });
}
