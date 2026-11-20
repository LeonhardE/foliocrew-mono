"use client";

import { useTranslations } from "next-intl";
import { useEffect, useRef, useState, type FormEvent } from "react";
import {
  INVITATION_EMAIL,
  WORKSPACE_INVITATIONS,
  type Invitation,
  type InvitationPage,
} from "@/lib/workspace-invitations";
import { useAuth } from "./AuthProvider";
import styles from "./SettingsInvitations.module.css";

type Confirmation =
  | { action: "send"; email: string; replaceRevision?: string }
  | { action: "revoke"; invitation: Invitation };

function Invitations({ sessionKey }: { sessionKey: string }) {
  const { requestPrivate } = useAuth();
  const t = useTranslations("settings.invitations");
  const [allowed, setAllowed] = useState(false);
  const [page, setPage] = useState<InvitationPage | null>(null);
  const [address, setAddress] = useState("");
  const [confirmation, setConfirmation] = useState<Confirmation | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<"invalidEmail" | "requestFailed" | null>(null);
  const [updated, setUpdated] = useState<Invitation | null>(null);
  const session = useRef<AbortController | null>(null);
  const pending = useRef(false);

  useEffect(() => {
    const controller = new AbortController();
    session.current = controller;
    void requestPrivate("user", `${WORKSPACE_INVITATIONS}/capability`, sessionKey, {
      signal: controller.signal,
    })
      .then((reply) => (reply.ok ? reply.json() : null))
      .then((value) => {
        if (!controller.signal.aborted) setAllowed(value?.canManageInvitations === true);
      })
      .catch(() => {});
    return () => controller.abort();
  }, [requestPrivate, sessionKey]);

  async function operation(
    suffix: string,
    method: "GET" | "POST",
    json: unknown,
    apply: (response: Response) => Promise<void>,
  ) {
    const signal = session.current?.signal;
    if (!signal || signal.aborted || pending.current) return;
    pending.current = true;
    setBusy(true);
    setError(null);
    setUpdated(null);
    try {
      const reply = await requestPrivate("user", WORKSPACE_INVITATIONS + suffix, sessionKey, {
        method,
        signal,
        json,
      });
      if (signal.aborted) return;
      if (reply.status === 403) {
        setAllowed(false);
        setPage(null);
        setAddress("");
        setConfirmation(null);
        return;
      }
      if (!reply.ok) throw Error("Invitation request failed.");
      await apply(reply);
    } catch {
      if (!signal.aborted) setError("requestFailed");
    } finally {
      pending.current = false;
      if (!signal.aborted) setBusy(false);
    }
  }

  function load(after?: string) {
    return operation(after ? `?after=${after}` : "", "GET", undefined, async (reply) => {
      const result = (await reply.json()) as InvitationPage;
      if (session.current?.signal.aborted) return;
      setPage((previous) => {
        if (!after || !previous) return result;
        const seen = new Set(previous.items.map((item) => item.id));
        return {
          items: [...previous.items, ...result.items.filter((item) => !seen.has(item.id))],
          nextCursor: result.nextCursor,
        };
      });
    });
  }

  function edit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const email = address.trim().toLowerCase();
    if (email.length > 74 || !INVITATION_EMAIL.test(email)) {
      setError("invalidEmail");
      return;
    }
    setError(null);
    setConfirmation({ action: "send", email });
  }

  function change(suffix: string, json?: unknown) {
    return operation(suffix, "POST", json, async (reply) => {
      const item = (await reply.json()) as Invitation;
      if (session.current?.signal.aborted) return;
      setPage((previous) => ({
        items: [item, ...(previous?.items.filter((row) => row.id !== item.id) ?? [])],
        nextCursor: previous?.nextCursor ?? null,
      }));
      setConfirmation(null);
      setAddress("");
      setUpdated(item);
    });
  }

  function confirm() {
    if (confirmation?.action === "revoke") {
      const { id, revision } = confirmation.invitation;
      void change(`/${id}/${revision}/revoke`);
    } else if (confirmation?.action === "send") {
      const { email, replaceRevision } = confirmation;
      void change("", { email, ...(replaceRevision ? { replaceRevision } : {}) });
    }
  }

  if (!allowed) return null;

  return (
    <section className={styles.panel} aria-labelledby="settings-user-management">
      <h2 id="settings-user-management">{t("title")}</h2>
      <details
        onToggle={(event) => {
          if (event.currentTarget.open && !page) void load();
        }}
      >
        <summary>{t("inviteUser")}</summary>
        <div className={styles.content} aria-busy={busy}>
          <form className={styles.form} onSubmit={edit}>
            <label htmlFor="settings-invite-email">{t("email")}</label>
            <div className={styles.actions}>
              <input
                type="email"
                id="settings-invite-email"
                autoComplete="off"
                required
                maxLength={74}
                value={address}
                disabled={busy || !page || confirmation !== null}
                onChange={(event) => setAddress(event.target.value)}
              />
              <button type="submit" disabled={busy || !page || confirmation !== null}>
                {t("review")}
              </button>
            </div>
          </form>
          {confirmation && (
            <div className={styles.confirmation}>
              <p>
                {confirmation.action === "send"
                  ? t("confirmSend", { email: confirmation.email })
                  : t("confirmRevoke", { email: confirmation.invitation.email })}
              </p>
              <div className={styles.actions}>
                <button type="button" onClick={confirm} disabled={busy}>
                  {t(confirmation.action === "send" ? "send" : "revoke")}
                </button>
                <button type="button" onClick={() => setConfirmation(null)} disabled={busy}>
                  {t("cancel")}
                </button>
              </div>
            </div>
          )}
          {error && (
            <p className={styles.error} role="alert">
              {t(error)}
            </p>
          )}
          <p className={styles.status} role="status">
            {busy
              ? t("working")
              : updated
                ? t("updated", {
                    email: updated.email,
                    status: t(`status.${updated.status}`),
                  })
                : null}
          </p>
          {page ? (
            <>
              <div className={styles.listHeading}>
                <h3>{t("list")}</h3>
                <button
                  type="button"
                  disabled={busy || confirmation !== null}
                  onClick={() => void load()}
                >
                  {t("refresh")}
                </button>
              </div>
              {page.items.length === 0 ? (
                <p className={styles.empty}>{t("empty")}</p>
              ) : (
                <ul className={styles.list}>
                  {page.items.map((item) => (
                    <li key={item.id} className={styles.row}>
                      <div>
                        <span className={styles.address}>{item.email}</span>
                        <span className={styles.state}>{t(`status.${item.status}`)}</span>
                      </div>
                      <div className={styles.actions}>
                        {item.canRetry && (
                          <button
                            type="button"
                            disabled={busy || confirmation !== null}
                            onClick={() => void change(`/${item.id}/${item.revision}/retry`)}
                            aria-label={t("retryFor", { email: item.email })}
                          >
                            {t("retry")}
                          </button>
                        )}
                        {item.canRevoke && (
                          <button
                            type="button"
                            disabled={busy || confirmation !== null}
                            onClick={() => setConfirmation({ action: "revoke", invitation: item })}
                            aria-label={t("revokeFor", { email: item.email })}
                          >
                            {t("revoke")}
                          </button>
                        )}
                        {(item.status === "expired" || item.status === "revoked") && (
                          <button
                            type="button"
                            disabled={busy || confirmation !== null}
                            onClick={() =>
                              setConfirmation({
                                action: "send",
                                email: item.email,
                                replaceRevision: item.revision,
                              })
                            }
                            aria-label={t("reissueFor", { email: item.email })}
                          >
                            {t("reissue")}
                          </button>
                        )}
                      </div>
                    </li>
                  ))}
                </ul>
              )}
              {page.nextCursor && (
                <button
                  type="button"
                  disabled={busy || confirmation !== null}
                  onClick={() => void load(page.nextCursor ?? undefined)}
                >
                  {t("more")}
                </button>
              )}
            </>
          ) : (
            !busy && (
              <button type="button" onClick={() => void load()}>
                {t("refresh")}
              </button>
            )
          )}
        </div>
      </details>
    </section>
  );
}

export default function SettingsInvitations() {
  const { ownerCapabilities, status, sessionKey } = useAuth();
  if (!ownerCapabilities?.invitationManagement || status !== "authenticated" || !sessionKey)
    return null;
  return <Invitations key={sessionKey} sessionKey={sessionKey} />;
}
