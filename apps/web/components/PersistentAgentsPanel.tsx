"use client";
import { useCallback, useEffect, useRef, useState, type MouseEvent } from "react";
import { useLocale, useTranslations } from "next-intl";
import { useAuth } from "./AuthProvider";
import type { HoldingsWorkspace } from "./useHoldingsWorkspace";
import type { PersistentWorkspaceModel } from "./usePersistentWorkspace";
import {
  DEFAULT_CONNECTION_SECONDS,
  TEMPORARY_CONNECTION_SECONDS,
  type PersistentConnection,
  type PersistentConnectionView,
  type PersistentTask,
} from "@/lib/persistent-experience-controller";
import {
  agentAuthorizationHandoff,
  type AgentAuthorizationHandoff,
} from "@/lib/agent-authorization";
import {
  nativeHandoff,
  connectNativeOwnerBridge,
  type NativeOwnerBridge,
} from "@/lib/native-owner-bridge";
import { providerGroups } from "@/lib/provider-groups";
import { BRANDED_AGENT_ORIGIN } from "@/lib/agent-connections";
import { ProviderMark } from "./ProviderMark";
import { ReportDialog } from "./ReportDialog";
import { LoadingIndicator, InlineError } from "./WorkspaceFeedback";
import styles from "./AgentsPanel.module.css";
const CONTRACT = "folioview.agent-workspace.v2.0";
const PUBLIC_MUSE_CLIENT_ID = "foliocrew-muse-prod";
type Json = Record<string, any>;
const providerName = (provider: string) => (provider === "chatgpt" ? "ChatGPT" : "Muse");
export function AgentConnectionDuration({
  seconds,
  pending,
  busy,
  onChange,
}: {
  seconds: number;
  pending: boolean;
  busy: boolean;
  onChange: (seconds: number) => void;
}) {
  const t = useTranslations("agentAccess");
  return (
    <>
      <label className={styles.durationChoice}>
        {t("durationLabel")}
        <select
          value={seconds}
          disabled={pending || busy}
          onChange={(e) => {
            const seconds = Number(e.target.value);
            if ([DEFAULT_CONNECTION_SECONDS, TEMPORARY_CONNECTION_SECONDS].includes(seconds))
              onChange(seconds);
          }}
        >
          <option value={DEFAULT_CONNECTION_SECONDS}>{t("duration90Days")}</option>
          <option value={TEMPORARY_CONNECTION_SECONDS}>{t("duration15Minutes")}</option>
        </select>
      </label>
      {pending && <p className={styles.note}>{t("durationPending")}</p>}
    </>
  );
}
export function PersistentAgentsPanel({
  workspace,
  model,
  origin,
  hubOrigin,
  brandOrigin,
  active,
}: {
  workspace: HoldingsWorkspace;
  model: PersistentWorkspaceModel;
  origin: string | null;
  hubOrigin?: string | null;
  brandOrigin?: string | null;
  active: boolean;
}) {
  const t = useTranslations("agentAccess"),
    locale = useLocale(),
    auth = useAuth();
  const [accountBusy, setAccountBusy] = useState(false);
  const [bridge, setBridge] = useState<NativeOwnerBridge | null>(null),
    [account, setAccount] = useState<{ owner: string; value: Json } | null>(null),
    [confirmedAccountOwner, setConfirmedAccountOwner] = useState<string | null>(null),
    [help, setHelp] = useState<string | null>(null),
    [copiedMessage, setCopiedMessage] = useState<string | null>(null),
    [handoffReady, setHandoffReady] = useState(false),
    [linkError, setLinkError] = useState(false),
    [readingAuthorization, setReadingAuthorization] = useState(false),
    [moreOptionsOpen, setMoreOptionsOpen] = useState(false),
    [approvedProvider, setApprovedProvider] = useState<string | null>(null),
    [now, setNow] = useState(() => Date.now() / 1000);
  const handoff = useRef<AgentAuthorizationHandoff | null>(null),
    reviewedHandoff = useRef<{ value: AgentAuthorizationHandoff; scope: string } | null>(null),
    oldOwner = useRef(model.owner);
  const scope =
    model.owner && workspace.owner === model.owner && workspace.phase === "unlocked"
      ? `${model.owner}:${workspace.vault?.vaultId ?? "unavailable"}:${workspace.vaultGeneration}`
      : null;
  const live = useRef({ scope, owner: model.owner, active, unlocked: model.unlocked });
  live.current = { scope, owner: model.owner, active, unlocked: model.unlocked };
  const [authorization, setAuthorization] = useState<{
    scope: string;
    value: Json;
    selected: string[];
    lifetimeSeconds: number;
  } | null>(null);
  const nextClockUpdate = model.views.reduce((next, { credential }) => {
    const expiry = credential?.expiresAt;
    return expiry > now ? Math.min(next, expiry) : next;
  }, now + 60);
  useEffect(() => {
    if (!active || !model.unlocked) return;
    const timer = setTimeout(
      () => setNow(Date.now() / 1000),
      Math.max(0, Math.ceil(nextClockUpdate * 1000 - Date.now())),
    );
    return () => clearTimeout(timer);
  }, [active, model.unlocked, nextClockUpdate]);
  useEffect(() => {
    reviewedHandoff.current = null;
    setAuthorization(null);
    setApprovedProvider(null);
  }, [scope]);
  useEffect(() => {
    if (oldOwner.current && oldOwner.current !== model.owner) {
      handoff.current = null;
      reviewedHandoff.current = null;
      setHandoffReady(false);
      setAccount(null);
      setConfirmedAccountOwner(null);
    }
    oldOwner.current = model.owner;
  }, [model.owner]);
  useEffect(() => {
    if (!active || !origin) return;
    const trusted = hubOrigin && brandOrigin ? [hubOrigin, brandOrigin] : (hubOrigin ?? origin);
    try {
      const value = agentAuthorizationHandoff(window.location.hash, trusted);
      if (value) {
        handoff.current = value;
        setHandoffReady(true);
        setMoreOptionsOpen(false);
        setApprovedProvider(null);
        window.history.replaceState(null, "", "/agents");
      }
    } catch {
      setLinkError(true);
      window.history.replaceState(null, "", "/agents");
    }
    const abort = new AbortController();
    let attached: NativeOwnerBridge | null = null;
    try {
      const value = nativeHandoff(window.location.search);
      if (value) {
        setConfirmedAccountOwner(null);
        void connectNativeOwnerBridge(value, trusted, abort.signal)
          .then((v) => {
            if (abort.signal.aborted) v.close();
            else {
              attached = v;
              setBridge(v);
            }
          })
          .catch(() => {
            if (!abort.signal.aborted) setLinkError(true);
          });
      }
    } catch {
      setLinkError(true);
    }
    return () => {
      abort.abort();
      attached?.close();
      setBridge(null);
    };
  }, [active, origin, hubOrigin, brandOrigin]);
  useEffect(() => {
    if (!bridge || !model.owner || !active) return;
    const owner = model.owner,
      abort = new AbortController();
    void auth
      .requestNativeAccount(bridge, "pending", { contractVersion: CONTRACT }, owner, abort.signal)
      .then((value) => {
        if (!abort.signal.aborted && live.current.owner === owner)
          setAccount({ owner, value: value as Json });
      })
      .catch(() => {
        if (!abort.signal.aborted) setLinkError(true);
      });
    return () => abort.abort();
  }, [bridge, model.owner, active, auth.requestNativeAccount]);
  const { execute, reload } = model;
  const readAuthorization = useCallback(async () => {
    const original = live.current.scope,
      value = handoff.current;
    if (!original || !value || !live.current.unlocked) return;
    reviewedHandoff.current = { value, scope: original };
    setReadingAuthorization(true);
    const reviewed = await execute((c) => c.inspectAuthorization(value));
    setReadingAuthorization(false);
    if (live.current.active && live.current.scope === original && handoff.current === value) {
      if (reviewed) {
        setAuthorization({
          scope: original,
          value: reviewed,
          lifetimeSeconds: reviewed.pendingLifetimeSeconds ?? DEFAULT_CONNECTION_SECONDS,
          selected: reviewed.renewing
            ? reviewed.tasks.map((task: PersistentTask) => task.taskId)
            : [],
        });
      } else if (!live.current.unlocked) {
        reviewedHandoff.current = null;
      }
      void reload(false);
    }
  }, [execute, reload]);
  useEffect(() => {
    const value = handoff.current;
    if (!active || !model.unlocked || model.busy || !scope || !handoffReady || !value) return;
    if (reviewedHandoff.current?.value === value && reviewedHandoff.current.scope === scope) return;
    void readAuthorization();
  }, [active, model.unlocked, model.busy, scope, handoffReady, readAuthorization]);
  const approveAccount = async () => {
    if (!bridge || !model.owner || !accountVault || accountBusy) return;
    const owner = model.owner;
    setAccountBusy(true);
    try {
      await auth.requestNativeAccount(
        bridge,
        "approve",
        { contractVersion: CONTRACT, vaultId: accountVault.vaultId },
        owner,
      );
      if (live.current.owner !== owner || !live.current.active) return;
      setAccount(null);
      setConfirmedAccountOwner(owner);
      bridge.close();
      setBridge(null);
      window.history.replaceState(null, "", "/agents");
      if (live.current.scope) await model.reload();
    } catch {
      if (live.current.owner === owner) setLinkError(true);
    } finally {
      setAccountBusy(false);
    }
  };
  const confirmAuthorization = async () => {
    const value = authorization?.scope === scope ? authorization : null,
      secret = handoff.current;
    if (!value || !secret) return;
    const result = await model.execute((c) =>
      c.authorize(secret, value.value, value.selected, value.lifetimeSeconds),
    );
    if (result && live.current.scope === value.scope) {
      handoff.current = null;
      reviewedHandoff.current = null;
      setHandoffReady(false);
      setAuthorization(null);
      setCopiedMessage(null);
      setApprovedProvider(value.value.connection.provider);
      await model.reload();
    }
  };
  const date = (value: number) =>
    new Intl.DateTimeFormat(
      locale,
      Math.abs(value - now) <= 86400
        ? { dateStyle: "medium", timeStyle: "short" }
        : { dateStyle: "medium" },
    ).format(value * 1000);
  function credentialExpiry(view: PersistentConnectionView | null) {
    const credential = view?.credential;
    if (
      !model.unlocked ||
      view?.connection.status !== "active" ||
      !credential?.expiresAt ||
      !["active", "expiring", "expired"].includes(credential.status)
    )
      return null;
    const expired = credential.status === "expired" || credential.expiresAt <= now;
    return t(expired ? "expiredAt" : "expires", { date: date(credential.expiresAt) });
  }
  const status = (view: (typeof model.views)[number]) => {
    const value = view.credential;
    if (!value) return "statusUnavailable";
    if (!["active", "expiring"].includes(value.status) || value.expiresAt <= now)
      return "reauthorize";
    return value.expiresAt - now <= 604800 ? "expiring" : "connected";
  };
  const ready = model.unlocked && model.loaded,
    readError = model.loadError,
    refreshing = model.loading,
    checking = model.unlocked && !ready && !readError,
    canChangeConnection = ready && !readError && !model.busy;
  const groups = providerGroups(ready ? model.views : [], ready ? model.providerStates : {}, now);
  const helpGroup = groups.find((group) => group.provider === help);
  const helpHasConnection = Boolean(helpGroup?.current || helpGroup?.accountStep);
  const helpIsPairing = helpGroup?.accountStep === "pairingNeeded";
  const connectorOrigin = brandOrigin ?? origin;
  const connectorAddress = connectorOrigin && `${connectorOrigin}/mcp/v3`;
  const connectionPrompt =
    help && helpIsPairing
      ? t("pairingPrompt")
      : connectorAddress && help
        ? help === "chatgpt"
          ? t("chatgptConnectionPrompt", { address: connectorAddress })
          : connectorOrigin === BRANDED_AGENT_ORIGIN
            ? t("museConnectionPromptWithClient", {
                address: connectorAddress,
                clientId: PUBLIC_MUSE_CLIENT_ID,
              })
            : t("museConnectionPrompt", { address: connectorAddress })
        : null;
  const finishConnectionMessage = t("finishConnectionPrompt");
  const copyMessage = async (message: string) => {
    try {
      await navigator.clipboard.writeText(message);
      setCopiedMessage(message);
    } catch {
      setCopiedMessage(null);
    }
  };
  const needsPasskey = workspace.phase === "needs-vault";
  const checkingPasskey = workspace.phase === "checking";
  const taskLink = (event: MouseEvent<HTMLAnchorElement>, taskId: string) => {
    if (
      event.button === 0 &&
      !event.metaKey &&
      !event.ctrlKey &&
      !event.shiftKey &&
      !event.altKey
    ) {
      event.preventDefault();
      window.history.pushState(null, "", `/tasks#task/${taskId}`);
    }
  };
  const currentAuthorization =
      model.unlocked && authorization?.scope === scope ? authorization : null,
    currentAccount = account?.owner === model.owner ? account.value : null;
  // Account OAuth only links a signed-in user's existing vault. The separate
  // Agent pairing operation still signs in the unlocked Owner Worker.
  const accountVault =
    currentAccount &&
    workspace.authenticated &&
    workspace.owner === model.owner &&
    (workspace.phase === "locked" || workspace.phase === "unlocked")
      ? workspace.vault
      : null;
  const accountConfirmed = Boolean(model.owner && confirmedAccountOwner === model.owner);
  const cancel = () => {
    handoff.current = null;
    reviewedHandoff.current = null;
    setHandoffReady(false);
    setAuthorization(null);
  };
  const loadState =
    !workspace.authenticated ||
    !model.unlocked ||
    workspace.phase !== "unlocked" ||
    workspace.owner !== model.owner
      ? "locked"
      : readError || linkError || model.error
        ? "error"
        : !active ||
            !origin ||
            refreshing ||
            checking ||
            model.busy ||
            !ready ||
            model.displayState !== "ready"
          ? "loading"
          : "ready";
  return (
    <section
      className={styles.panel}
      aria-labelledby="agent-access-title"
      data-load-scope="agent-connections"
      data-load-state={loadState}
      aria-busy={checking || refreshing || model.busy}
    >
      <header className={styles.heading}>
        <div>
          <h1 id="agent-access-title">{t("title")}</h1>
          <p>{t("description")}</p>
        </div>
        <button
          className={styles.secondary}
          disabled={model.busy || model.loading}
          onClick={() => {
            void model.reload();
          }}
        >
          {t("refresh")}
        </button>
      </header>
      {!workspace.authenticated ? (
        <div className={styles.unlock}>
          <p>{t("signInHelp")}</p>
          <button className={styles.primary} onClick={() => void workspace.signIn()}>
            {t("signIn")}
          </button>
        </div>
      ) : !model.unlocked && !accountVault && !accountConfirmed ? (
        <div className={styles.unlock}>
          <p role={checkingPasskey ? "status" : undefined}>
            {t(checkingPasskey ? "loading" : needsPasskey ? "setUpPasskeyHelp" : "unlockHelp")}
          </p>
          {checkingPasskey ? null : workspace.phase === "needs-device" ? (
            <a href="/settings">{t("deviceNeeded")}</a>
          ) : (
            <button
              className={styles.primary}
              disabled={Boolean(workspace.busy || (needsPasskey && !workspace.vaultConfigured))}
              onClick={() =>
                void (needsPasskey
                  ? workspace.create()
                  : workspace.unlock({ forResults: true, enableState: true }))
              }
            >
              {t(needsPasskey ? "setUpPasskey" : "unlock")}
            </button>
          )}
          {needsPasskey && workspace.error && (
            <a href="/settings#settings-security-title">{t("passkeySettings")}</a>
          )}
        </div>
      ) : null}
      {model.waitingForService && <p role="status">{t("waitingForService")}</p>}
      {(linkError || (model.error && !model.loadError)) && (
        <p role="alert" className={styles.warning}>
          {t(
            model.error === "review_changed"
              ? "reviewChanged"
              : model.error === "persistent_operation_pending"
                ? "continueHelp"
                : "requestFailed",
          )}
        </p>
      )}
      {currentAccount && (
        <div className={styles.setup}>
          <h2>
            {t("accountTitle", { provider: providerName(currentAccount.provider ?? "muse") })}
          </h2>
          <p>{t("accountHelp")}</p>
          <button
            className={styles.primary}
            disabled={accountBusy || !accountVault}
            onClick={() => void approveAccount()}
          >
            {t("confirmAccount")}
          </button>
        </div>
      )}
      {accountConfirmed && (
        <div className={styles.setup}>
          <h2>{t("accountConfirmed")}</h2>
          <p role="status">{t("accountReturnHelp")}</p>
          <button className={styles.primary} onClick={() => window.close()}>
            {t("returnToAuthorization")}
          </button>
        </div>
      )}
      {approvedProvider && model.unlocked && (
        <div className={`${styles.setup} ${styles.authorization}`}>
          <h2 role="status">{t("authorizationSaved")}</h2>
          <p id="finish-agent-instructions">
            {t("returnAfterAuthorization", { provider: providerName(approvedProvider) })}
          </p>
          <textarea
            aria-label={t("connectionMessage")}
            aria-describedby="finish-agent-instructions"
            className={styles.connectMessage}
            rows={3}
            value={finishConnectionMessage}
            readOnly
          />
          <button className={styles.secondary} onClick={() => copyMessage(finishConnectionMessage)}>
            {t(copiedMessage === finishConnectionMessage ? "copied" : "copyConnectionMessage")}
          </button>
        </div>
      )}
      {handoffReady && (
        <div className={`${styles.setup} ${styles.authorization}`}>
          <h2>{t("authorizeTitle")}</h2>
          {!currentAuthorization ? (
            <p role="status">
              {t(readingAuthorization ? "preparingAuthorization" : "authorizeHelp")}
            </p>
          ) : (
            <>
              <p>
                {currentAuthorization.value.providerState
                  ? t(
                      currentAuthorization.value.providerState.retirementCandidates.length
                        ? "replaceReview"
                        : "newConnectionReview",
                      {
                        count: currentAuthorization.value.providerState.retirementCandidates.length,
                        provider: providerName(currentAuthorization.value.connection.provider),
                      },
                    )
                  : t(currentAuthorization.value.renewing ? "restoreHelp" : "chooseTasks", {
                      provider: providerName(currentAuthorization.value.connection.provider),
                    })}
              </p>
              {currentAuthorization.value.providerState && (
                <p className={styles.note}>{t("taskReview")}</p>
              )}
              {!currentAuthorization.value.providerState &&
                (currentAuthorization.value.tasks.length ? (
                  <ul className={styles.taskChoices}>
                    {currentAuthorization.value.tasks.map((task: PersistentTask) => (
                      <li key={task.taskId}>
                        {currentAuthorization.value.renewing ? (
                          <span>{task.title}</span>
                        ) : (
                          <label>
                            <input
                              type="checkbox"
                              checked={currentAuthorization.selected.includes(task.taskId)}
                              onChange={(e) =>
                                setAuthorization((v) =>
                                  v
                                    ? {
                                        ...v,
                                        selected: e.target.checked
                                          ? [...v.selected, task.taskId]
                                          : v.selected.filter((id) => id !== task.taskId),
                                      }
                                    : v,
                                )
                              }
                            />
                            {task.title}
                          </label>
                        )}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p>{t("noAvailableTasks")}</p>
                ))}
              <details
                className={styles.authorizationOptions}
                open={moreOptionsOpen}
                onToggle={(event) => setMoreOptionsOpen(event.currentTarget.open)}
              >
                <summary>{t("moreOptions")}</summary>
                <AgentConnectionDuration
                  seconds={currentAuthorization.lifetimeSeconds}
                  pending={currentAuthorization.value.pendingLifetimeSeconds != null}
                  busy={model.busy}
                  onChange={(lifetimeSeconds) =>
                    setAuthorization((v) => (v ? { ...v, lifetimeSeconds } : v))
                  }
                />
              </details>
            </>
          )}
          <div className={styles.actions}>
            {currentAuthorization ? (
              <button
                className={styles.primary}
                disabled={model.busy || !workspace.canWriteState}
                onClick={() => void confirmAuthorization()}
              >
                {t(
                  model.busy
                    ? "savingAuthorization"
                    : currentAuthorization.value.renewing &&
                        !currentAuthorization.value.providerState
                      ? "confirmRestore"
                      : "confirm",
                )}
              </button>
            ) : model.unlocked && !readingAuthorization ? (
              <button
                className={styles.primary}
                disabled={model.busy}
                onClick={() => void readAuthorization()}
              >
                {t("review")}
              </button>
            ) : null}
            <button className={styles.textButton} disabled={model.busy} onClick={cancel}>
              {t("cancel")}
            </button>
          </div>
        </div>
      )}
      <LoadingIndicator
        busy={checking || refreshing}
        hasContent={ready}
        label={t(ready ? "refreshing" : "loading")}
      />
      {model.unlocked && readError && (
        <InlineError
          message={t(ready ? "refreshFailed" : "loadFailed")}
          retryLabel={t("refresh")}
          onRetry={() => {
            void model.reload();
          }}
        />
      )}
      <div className={styles.connectionGrid}>
        {groups.map((group) => {
          const view = group.current,
            connected = view && status(view) === "connected" && !group.accountStep,
            pending = connected ? null : group.pending,
            expiry = credentialExpiry(view),
            action =
              connected || group.accountStep === "accountConnecting"
                ? null
                : group.accountStep === "pairingNeeded"
                  ? "finishPairing"
                  : group.accountStep === "accountLinkExpired"
                    ? "retryAccountLink"
                    : view?.connection.status === "active"
                      ? "reauthorizeButton"
                      : "connect",
            value = !model.unlocked
              ? "unlockStatus"
              : !ready
                ? readError
                  ? "statusUnavailable"
                  : "loading"
                : group.reviewRequired
                  ? "reviewRequired"
                  : (group.accountStep ?? (view ? status(view) : "notConnected"));
          return (
            <article
              key={group.provider}
              className={styles.setup}
              aria-busy={checking || refreshing}
            >
              <div className={styles.heading}>
                <div className={styles.providerHeader}>
                  <ProviderMark provider={group.provider} />
                  <h2>{providerName(group.provider)}</h2>
                </div>
                <span
                  className={styles.stateBadge}
                  data-checking={checkingPasskey || checking || refreshing}
                >
                  {t(checkingPasskey ? "loading" : needsPasskey ? "passkeyRequired" : value)}
                </span>
              </div>
              {expiry && !group.accountStep && <p className={styles.note}>{expiry}</p>}
              {group.reviewRequired && <p className={styles.note}>{t("reviewConnections")}</p>}
              {group.accountStep && (
                <p className={styles.note}>
                  {t(`${group.accountStep}Help`, { provider: providerName(group.provider) })}
                </p>
              )}
              {model.unlocked && view?.tasks.length ? (
                <ul className={styles.taskLinks}>
                  {view.tasks.map((task) => (
                    <li key={task.taskId}>
                      <a
                        href={`/tasks#task/${task.taskId}`}
                        onClick={(e) => taskLink(e, task.taskId)}
                      >
                        {task.title}
                      </a>
                    </li>
                  ))}
                </ul>
              ) : null}
              <div className={styles.actions}>
                {action && (
                  <button
                    className={styles.primary}
                    disabled={!connectorAddress || !model.enabled || !canChangeConnection}
                    onClick={() => {
                      setHelp(group.provider);
                      setCopiedMessage(null);
                    }}
                  >
                    {t(action, { provider: providerName(group.provider) })}
                  </button>
                )}
                {pending && (
                  <button
                    className={styles.secondary}
                    disabled={!canChangeConnection || !workspace.canWriteState}
                    onClick={() => void model.continueOperation(pending.connection)}
                  >
                    {t("continue")}
                  </button>
                )}
                {view?.connection.status === "active" && (
                  <button
                    className={styles.textButton}
                    disabled={!canChangeConnection}
                    onClick={() => {
                      void model.disconnect(view.connection);
                    }}
                  >
                    {t(connected ? "revokeAccess" : "disconnect")}
                  </button>
                )}
              </div>
            </article>
          );
        })}
        {["claude", "gemini"].map((provider) => (
          <article className={styles.unsupported} key={provider}>
            <ProviderMark provider={provider} />
            <strong>{provider === "claude" ? "Claude" : "Gemini"}</strong>
            <span>{t("notSupported")}</span>
          </article>
        ))}
      </div>
      <ReportDialog
        id="connect-agent"
        open={Boolean(help)}
        identity={`${model.owner}:${help}`}
        title={t("connect", { provider: providerName(help ?? "muse") })}
        closeLabel={t("close")}
        onClose={() => setHelp(null)}
      >
        {help && connectionPrompt && (
          <>
            <div className={styles.actions}>
              <a
                className={`${styles.primary} ${styles.providerLink}`}
                href={help === "chatgpt" ? "https://chatgpt.com/plugins" : "https://muse.ai/"}
                target="_blank"
                rel="noopener noreferrer"
                onClick={model.expectProviderReturn}
              >
                {t("openProvider", { provider: providerName(help) })}
              </a>
            </div>
            <p id="connect-agent-instructions">
              {t(
                helpIsPairing
                  ? "pairingNeededHelp"
                  : help === "chatgpt"
                    ? "chatgptConnectHelp"
                    : helpHasConnection
                      ? "reconnectHelp"
                      : "connectHelp",
                {
                  provider: providerName(help),
                },
              )}
            </p>
            {connectorAddress && !helpIsPairing && (
              <div className={styles.connectorAddress}>
                <span className={styles.note}>{t("serverAddress")}</span>
                <div className={styles.actions}>
                  <code>{connectorAddress}</code>
                  <button
                    className={styles.secondary}
                    onClick={() => copyMessage(connectorAddress)}
                  >
                    {t(copiedMessage === connectorAddress ? "copied" : "copyServerAddress")}
                  </button>
                </div>
              </div>
            )}
            <details className={styles.connectionInstructions} open={helpIsPairing || undefined}>
              <summary>{t("connectionMessage")}</summary>
              <textarea
                aria-label={t("connectionMessage")}
                aria-describedby="connect-agent-instructions"
                className={styles.connectMessage}
                rows={7}
                value={connectionPrompt}
                readOnly
              />
              <button className={styles.secondary} onClick={() => copyMessage(connectionPrompt)}>
                {t(copiedMessage === connectionPrompt ? "copied" : "copyConnectionMessage")}
              </button>
            </details>
          </>
        )}
      </ReportDialog>
      {workspace.authenticated && model.loaded && !model.enabled && !model.busy && (
        <p className={styles.note}>{t("notReady")}</p>
      )}
    </section>
  );
}
