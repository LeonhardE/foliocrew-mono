import { exact, type ResourceCatalogue, type ResourceRef } from "./resource-library";
import type { HoldingsWorkspace } from "@/components/useHoldingsWorkspace";

/** Display association only; the existing Worker and fresh action authority remain unchanged. */
export type HoldingsPublication = {
  owner: string;
  workspaceScope: string;
  ref: ResourceRef;
  sourceEpoch: number;
  snapshotId: string;
};
const identifier = (v: unknown): v is string =>
  typeof v === "string" && /^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$/.exec(v)?.[0] === v;
export const samePublicationRef = (
  a: ResourceRef | undefined | null,
  b: ResourceRef | undefined | null,
) =>
  Boolean(
    a &&
    b &&
    a.kind === b.kind &&
    a.sourceService === b.sourceService &&
    a.resourceId === b.resourceId &&
    a.incarnation === b.incarnation,
  );
export function bindHoldingsPublication(
  value: HoldingsPublication | null | undefined,
  owner: string | null,
  workspaceScope: string | null,
): HoldingsPublication | null {
  if (
    !owner ||
    !workspaceScope ||
    !exact(value, ["owner", "workspaceScope", "ref", "sourceEpoch", "snapshotId"]) ||
    value.owner !== owner ||
    value.workspaceScope !== workspaceScope ||
    !exact(value.ref, ["kind", "sourceService", "resourceId", "incarnation"]) ||
    value.ref.kind !== "holdings" ||
    value.ref.sourceService !== "portfolio" ||
    !identifier(value.ref.resourceId) ||
    !identifier(value.ref.incarnation) ||
    !Number.isSafeInteger(value.sourceEpoch) ||
    value.sourceEpoch < 1 ||
    !identifier(value.snapshotId)
  )
    return null;
  return { ...value, ref: { ...value.ref } };
}
export const sameHoldingsPublication = (
  a: HoldingsPublication | null,
  b: HoldingsPublication | null,
) =>
  Boolean(
    a &&
    b &&
    a.owner === b.owner &&
    a.workspaceScope === b.workspaceScope &&
    samePublicationRef(a.ref, b.ref) &&
    a.sourceEpoch === b.sourceEpoch &&
    a.snapshotId === b.snapshotId,
  );
export function catalogueHasPublishedHoldings(data: ResourceCatalogue, value: HoldingsPublication) {
  return (
    data.groups
      .flatMap((g) => (g.kind === "holdings" && g.sourceService === "portfolio" ? g.items : []))
      .filter(
        (item) =>
          samePublicationRef(item.ref, value.ref) &&
          item.sourceEpoch === value.sourceEpoch &&
          item.snapshotId === value.snapshotId &&
          item.state === "active" &&
          item.revision !== null &&
          item.revision > 0,
      ).length === 1
  );
}
export function workspaceHoldingsPublication(
  workspace: HoldingsWorkspace,
  workspaceScope: string,
): HoldingsPublication | null {
  const source = workspace.selectedSourceId
    ? workspace.sources.find((s) => s.resourceRef.resourceId === workspace.selectedSourceId)
    : workspace.sources.at(-1);
  const metadata = workspace.sourceMetadata,
    snapshotId = workspace.content?.data.snapshotId;
  if (
    !workspace.authenticated ||
    !workspace.owner ||
    workspace.phase !== "unlocked" ||
    workspace.needsDeviceApproval ||
    !workspace.vault ||
    workspace.newSource ||
    !source ||
    metadata?.state !== "active" ||
    !samePublicationRef(source.resourceRef, metadata.source?.resourceRef) ||
    source.sourceEpoch !== metadata.source?.sourceEpoch ||
    metadata.snapshotId !== snapshotId
  )
    return null;
  return bindHoldingsPublication(
    {
      owner: workspace.owner,
      workspaceScope,
      ref: source.resourceRef,
      sourceEpoch: source.sourceEpoch,
      snapshotId: snapshotId!,
    },
    workspace.owner,
    workspaceScope,
  );
}
