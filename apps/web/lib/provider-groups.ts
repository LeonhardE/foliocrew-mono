import type { PersistentConnectionView } from "./persistent-experience-controller";
type J = Record<string, any>;
// The Hub's native OAuth authorization code expires five minutes after approval.
const ACCOUNT_EXCHANGE_SECONDS = 300;
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
    const last =
      current ?? rows.find((v) => v.connection.connectionId === slot?.lastCredential?.connectionId);
    const newer = history
      .filter(
        (v) =>
          !v.error && !v.credential && v.connection.linkedAt > (last?.connection.linkedAt ?? 0),
      )
      .sort((a, b) => b.connection.linkedAt - a.connection.linkedAt)[0];
    const candidate = newer ?? current;
    const accountState = candidate?.connection.accountState;
    const accountStep =
      accountState === "connecting"
        ? candidate!.connection.linkedAt + ACCOUNT_EXCHANGE_SECONDS > now
          ? "accountConnecting"
          : "accountLinkExpired"
        : accountState === "connected" &&
            (newer ||
              (candidate?.credential?.status === "reauthorization_required" && !candidate.identity))
          ? "pairingNeeded"
          : null;
    const pending =
      [candidate, current].find(
        (view) => view?.pending && [undefined, "credential", "identity"].includes(view.pendingKind),
      ) ?? null;
    return { provider, current, history, accountStep, pending, reviewRequired };
  });
}
