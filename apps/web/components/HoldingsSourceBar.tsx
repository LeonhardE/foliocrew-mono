"use client";
import { useState, type ReactNode } from "react";
import { useLocale, useTranslations } from "next-intl";
import type { HoldingsWorkspace } from "./useHoldingsWorkspace";
import type { DisplayNamesModel } from "./useDisplayNames";
import type { ResourceLibraryModel } from "./useResourceLibrary";
import type { ResourceSelection } from "@/lib/resource-library";
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
  const items = library.catalogue.data?.groups.find((group) => group.kind === "holdings")?.items;
  const requested =
    sources.find((s) => s.resourceRef.resourceId === model.selectedSourceId) ??
    (!model.newSource ? sources.at(-1) : undefined);
  const deleted =
    model.sourceMetadata?.state === "deleted"
      ? model.sourceMetadata.source?.resourceRef
      : undefined;
  const rows = sources.filter((source) => {
    if (source === requested && model.sourceMutation?.action === "delete") return true;
    const { resourceId, incarnation } = source.resourceRef;
    return (
      !(deleted?.resourceId === resourceId && deleted.incarnation === incarnation) &&
      !items?.some(
        (item) =>
          item.state === "deleted" &&
          item.ref?.resourceId === resourceId &&
          item.ref.incarnation === incarnation,
      )
    );
  });
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
    ? items?.find(
        (item) =>
          item.ref?.resourceId === selectedRef.resourceId &&
          item.ref.incarnation === selectedRef.incarnation,
      )
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
        ) : (
          <p className={styles.note}>{t("lifecycle.empty")}</p>
        )}
        <LoadingIndicator busy={names.loading} hasContent label={t("manage.loadingNames")} />
        <div className={styles.sourceActions}>
          <button
            type="button"
            className={styles.secondary}
            disabled={blocked}
            onClick={() => void model.readStored()}
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
              {t("manage.add")}
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
      {model.sourceCreationId && !selected && children}
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
            if (selectedRef) void names.rename(selectedRef, draft.trim());
          }}
        >
          <label>
            {t("manage.name")}
            <input
              value={draft}
              maxLength={80}
              placeholder={title}
              disabled={!editable || names.busy || pending || !names.enabled}
              onChange={(e) => setDraft(e.target.value)}
            />
          </label>
          <button
            className={styles.primary}
            type="submit"
            disabled={
              !editable ||
              names.busy ||
              pending ||
              !names.enabled ||
              !draft.trim() ||
              draft.trim() === names.name(selectedRef!)
            }
          >
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
