"use client";
import { useState, type ReactNode } from "react";
import { useLocale, useTranslations } from "next-intl";
import type { HoldingsWorkspace } from "./useHoldingsWorkspace";
import type { DisplayNamesModel } from "./useDisplayNames";
import type { ResourceLibraryModel } from "./useResourceLibrary";
import type { ResourceRef, ResourceSelection } from "@/lib/resource-library";
import { useTasks } from "./useTasks";
import { ReportDialog } from "./ReportDialog";
import { InlineError, LoadingIndicator } from "./WorkspaceFeedback";
import styles from "./ResourcesPanel.module.css";
import { factsContent, formatHoldingsTime } from "@/lib/holdings-facts";

function RelatedTasks({
  model,
  source,
}: {
  model: HoldingsWorkspace;
  source: { resourceId: string; incarnation: string };
}) {
  const t = useTranslations("resources.manage"),
    tasks = useTasks(model, { active: true });
  const linked = tasks.items.filter((task) =>
    task.resourceBindings.some(
      (binding) =>
        binding.ref.resourceId === source.resourceId &&
        binding.ref.incarnation === source.incarnation,
    ),
  );
  return (
    <section aria-label={t("relatedTasks")}>
      <h3>{t("relatedTasks")}</h3>
      <LoadingIndicator busy={tasks.loading} hasContent={linked.length > 0} label={t("loading")} />
      {tasks.listError ? (
        <InlineError
          message={t("tasksFailed")}
          onRetry={() => void tasks.reloadTasks()}
          retryLabel={t("retry")}
        />
      ) : !tasks.loading && !linked.length ? (
        <p className={styles.note}>{t("noTasks")}</p>
      ) : null}
      <ul className={styles.relatedTasks}>
        {linked.map((task) => (
          <li key={task.taskId}>
            {tasks.taskNames[task.taskId] ? (
              <a
                href={`/tasks#task/${task.taskId}`}
                onClick={(event) => {
                  if (
                    event.button === 0 &&
                    !event.metaKey &&
                    !event.ctrlKey &&
                    !event.altKey &&
                    !event.shiftKey
                  ) {
                    event.preventDefault();
                    window.history.pushState(null, "", `/tasks#task/${task.taskId}`);
                  }
                }}
              >
                {tasks.taskNames[task.taskId]}
              </a>
            ) : tasks.nameErrors[task.taskId] ? (
              <button type="button" onClick={() => tasks.retryTaskName(task.taskId)}>
                {t("retryName")}
              </button>
            ) : (
              <LoadingIndicator busy label={t("loadingName")} />
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

export function HoldingsSourceBar({
  model,
  names,
  library,
  onCreateTask,
  onUpdate,
  children,
}: {
  model: HoldingsWorkspace;
  names: DisplayNamesModel;
  library: ResourceLibraryModel;
  onCreateTask?: (selection: ResourceSelection) => void;
  onUpdate: () => void;
  children: ReactNode;
}) {
  const locale = useLocale();
  const t = useTranslations("resources"),
    [settingsFor, setSettingsFor] = useState<string | null>(null),
    [draft, setDraft] = useState(""),
    [discardName, setDiscardName] = useState(false);
  const sources = model.sources ?? [];
  const catalogue = library.catalogue;
  const group = catalogue.data?.groups.find((item) => item.kind === "holdings");
  const items = !catalogue.stale && !catalogue.error ? group?.items : undefined;
  const requested =
    sources.find((source) => source.resourceRef.resourceId === model.selectedSourceId) ??
    (!model.newSource ? sources.at(-1) : undefined);
  const metadata = model.sourceMetadata;
  const sameIncarnation = (left: ResourceRef | undefined | null, right: ResourceRef) =>
    left?.kind === right.kind &&
    left.sourceService === right.sourceService &&
    left.resourceId === right.resourceId &&
    left.incarnation === right.incarnation;
  const states = sources.map((source) => {
    const receipt = group?.items.find((entry) => sameIncarnation(entry.ref, source.resourceRef));
    const item = items ? receipt : undefined;
    const direct = sameIncarnation(metadata?.source?.resourceRef, source.resourceRef)
      ? metadata
      : null;
    if (
      receipt?.state === "deleted" ||
      direct?.state === "deleted" ||
      (source === requested && model.sourceMutation?.action === "delete")
    )
      return { source, state: "deleted" };
    // The vault stores registration anchors, including deleted ones. An
    // anchor is never enough to offer a selectable source on a cold load.
    if (item?.sourceEpoch != null && item.sourceEpoch >= source.sourceEpoch)
      return { source, state: item.state };
    if (direct && direct.source.sourceEpoch >= source.sourceEpoch)
      return { source, state: direct.state };
    return { source, state: null };
  });
  const rows = states
    .filter(
      ({ state }) =>
        state !== null &&
        ["active", "ready", "empty", "revoking", "disconnected", "pending"].includes(state),
    )
    .map(({ source }) => source);
  const unchecked = states.some(({ state }) => state === null || state === "unavailable");
  const checking =
    unchecked && !library.offline && !catalogue.error && (catalogue.loading || !catalogue.data);
  const unavailable =
    unchecked &&
    !checking &&
    (library.offline ||
      catalogue.stale ||
      Boolean(catalogue.error) ||
      group?.status === "partial" ||
      group?.status === "unavailable" ||
      states.some(({ state }) => state === "unavailable"));
  const selected = requested && rows.includes(requested) ? requested : undefined;
  const selectedRef = selected?.resourceRef;
  const selectedKey = selectedRef
    ? JSON.stringify([names.scope, selectedRef.resourceId, selectedRef.incarnation])
    : null;
  const settings = selectedKey !== null && settingsFor === selectedKey;
  const title = selectedRef
    ? (names.name(selectedRef) ?? t("lifecycle.source", { number: sources.indexOf(selected!) + 1 }))
    : t("lifecycle.new");
  const sourceItem = selectedRef
    ? items?.find((item) => sameIncarnation(item.ref, selectedRef))
    : undefined;
  const operationBlocked = Boolean((model.busy && model.busy !== "reading") || names.busy);
  const blocked = operationBlocked || Boolean(model.preview);
  const pending = selectedRef && names.pending(selectedRef);
  const editable =
    model.canWriteState &&
    !model.busy &&
    !model.sourceMutation &&
    !model.sourceCreationId &&
    model.sourceMetadata?.state === "active";
  const normalizedName = draft.trim();
  const canSaveName = Boolean(
    selectedRef &&
    editable &&
    names.scope &&
    !names.busy &&
    !pending &&
    (!names.ready || names.enabled) &&
    normalizedName &&
    normalizedName !== names.name(selectedRef),
  );
  return (
    <>
      <div className={styles.sourceBar}>
        {model.newSource || rows.length > 0 ? (
          <label className={styles.sourcePicker}>
            <span className="sr-only">{t("lifecycle.select")}</span>
            <select
              value={model.newSource ? "new" : (selectedRef?.resourceId ?? "")}
              disabled={blocked}
              onChange={(e) => {
                setSettingsFor(null);
                void model.selectHoldingsSource(e.target.value);
              }}
            >
              {model.newSource && <option value="new">{t("lifecycle.new")}</option>}
              {!model.newSource && !selected && (
                <option value="" disabled>
                  {t("lifecycle.choose")}
                </option>
              )}
              {rows.map((source) => (
                <option key={source.resourceRef.resourceId} value={source.resourceRef.resourceId}>
                  {names.name(source.resourceRef) ??
                    t("lifecycle.source", { number: sources.indexOf(source) + 1 })}
                </option>
              ))}
            </select>
          </label>
        ) : checking ? (
          <LoadingIndicator busy label={t("loading")} />
        ) : unavailable ? (
          <p className={styles.warning} role="status">
            {t("lifecycle.sourcesUnavailable")}
          </p>
        ) : (
          <p className={styles.note}>{t("lifecycle.empty")}</p>
        )}
        <LoadingIndicator busy={names.loading} hasContent label={t("manage.loadingNames")} />
        <div className={styles.sourceActions}>
          <button
            type="button"
            className={styles.secondary}
            disabled={blocked || library.offline}
            onClick={() => {
              if (unchecked && !selected) void library.reload("catalogue");
              else void model.readStored();
            }}
          >
            {t("manage.refresh")}
          </button>
          {selected && !model.newSource && (
            <button
              type="button"
              className={styles.secondary}
              disabled={operationBlocked}
              onClick={() => {
                setDiscardName(false);
                setDraft(names.name(selected.resourceRef) ?? "");
                names.clearError();
                setSettingsFor(selectedKey);
              }}
            >
              {t("lifecycle.settings")}
            </button>
          )}
          {!model.newSource && sources.length < 10 && (
            <button
              type="button"
              className={styles.primary}
              disabled={
                operationBlocked ||
                Boolean(model.preview?.intent === "edit" || model.preview?.intent === "manual") ||
                !model.canWriteState ||
                Boolean(model.hasPending || model.sourceMutation || model.sourceCreationId)
              }
              onClick={model.beginNewSource}
            >
              {t("lifecycle.add")}
            </button>
          )}
        </div>
      </div>
      {selected && !model.newSource && model.content && (
        <p className={styles.note}>
          {model.content && factsContent(model.content) && !model.content.data.importSnapshot
            ? t("editing.manualSource")
            : "Wealthsimple"}{" "}
          ·{" "}
          {model.content
            ? t(
                factsContent(model.content) && model.content.data.editKind !== "import"
                  ? "editing.updatedAt"
                  : "importedAt",
                { time: formatHoldingsTime(model.content.fetchedAt, locale) },
              )
            : t("holdingsCsv")}
        </p>
      )}
      {(pending || model.sourceMutation || model.sourceCreationId) && !settings && selected && (
        <button
          type="button"
          className={styles.secondary}
          onClick={() => setSettingsFor(selectedKey)}
        >
          {t("manage.finishPending")}
        </button>
      )}
      {(model.sourceCreationId || model.sourceMutation) && !selected && children}
      <ReportDialog
        id="holdings-source-settings"
        open={settings && model.phase === "unlocked" && Boolean(selectedRef)}
        identity={selectedKey ?? names.scope ?? ""}
        title={t("lifecycle.settings")}
        closeLabel={t("manage.close")}
        onClose={() => setSettingsFor(null)}
      >
        <form
          className={styles.nameForm}
          onSubmit={(e) => {
            e.preventDefault();
            if (selectedRef && canSaveName) void names.rename(selectedRef, normalizedName);
          }}
        >
          <label>
            {t("manage.name")}
            <input
              value={draft}
              maxLength={80}
              placeholder={title}
              disabled={names.busy}
              onChange={(e) => setDraft(e.target.value)}
            />
          </label>
          <button className={styles.primary} type="submit" disabled={!canSaveName}>
            {t(names.busy ? "manage.savingName" : "manage.saveName")}
          </button>
        </form>
        {pending && selectedRef && (
          <div className={styles.warning}>
            <p>{t("manage.namePending")}</p>
            <div className={styles.sourceActions}>
              <button
                type="button"
                className={styles.secondary}
                disabled={names.busy}
                onClick={() => void names.recover(selectedRef)}
              >
                {t("manage.checkName")}
              </button>
              <button
                type="button"
                className={styles.secondary}
                disabled={names.busy || !editable}
                onClick={() => void names.recover(selectedRef, true)}
              >
                {t("manage.retryNameSave")}
              </button>
              <button
                type="button"
                className={styles.secondary}
                disabled={names.busy}
                onClick={() => setDiscardName(true)}
              >
                {t("manage.resumeEditing")}
              </button>
            </div>
          </div>
        )}
        {pending && selectedRef && discardName && (
          <div className={styles.warning} role="group" aria-label={t("manage.resumeEditing")}>
            <p>{t("manage.discardNameHelp")}</p>
            <div className={styles.sourceActions}>
              <button
                type="button"
                className={styles.secondary}
                disabled={names.busy}
                onClick={() => setDiscardName(false)}
              >
                {t("manage.keepWaiting")}
              </button>
              <button
                type="button"
                className={styles.primary}
                disabled={names.busy}
                onClick={() => {
                  void names.discard(selectedRef).then(() => setDiscardName(false));
                }}
              >
                {t("manage.confirmResume")}
              </button>
            </div>
          </div>
        )}
        {names.error && (
          <InlineError
            message={t(`manage.errors.${names.error}`)}
            retryLabel={t("manage.retry")}
            onRetry={() => void names.reload()}
          />
        )}
        {!names.loading && names.ready && !names.enabled && (
          <p className={styles.note}>{t("manage.namingUnavailable")}</p>
        )}
        <div className={styles.sourceActions}>
          <button
            type="button"
            className={styles.secondary}
            disabled={!editable}
            onClick={() => {
              setSettingsFor(null);
              onUpdate();
            }}
          >
            {t("manage.update")}
          </button>
          {onCreateTask && sourceItem && (
            <button
              type="button"
              className={styles.secondary}
              disabled={
                !editable ||
                library.catalogue.loading ||
                library.catalogue.stale ||
                Boolean(library.catalogue.error) ||
                !["active", "ready"].includes(sourceItem.state)
              }
              onClick={() => {
                setSettingsFor(null);
                library.useForTask(sourceItem, onCreateTask);
              }}
            >
              {t("manage.useInTask")}
            </button>
          )}
          <a
            href="/agents"
            className={styles.secondary}
            onClick={(event) => {
              if (
                !event.metaKey &&
                !event.ctrlKey &&
                !event.shiftKey &&
                !event.altKey &&
                event.button === 0
              ) {
                event.preventDefault();
                setSettingsFor(null);
                window.history.pushState(null, "", "/agents");
              }
            }}
          >
            {t("manage.sharing")}
          </a>
        </div>
        {settings && selectedRef && <RelatedTasks model={model} source={selectedRef} />}
        <details className={styles.advanced}>
          <summary>{t("manage.advanced")}</summary>
          {children}
        </details>
      </ReportDialog>
    </>
  );
}
