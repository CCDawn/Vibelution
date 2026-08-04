/**
 * SC inject: storage open actions for the selected run artifacts directory.
 * Route only supplies artifacts snapshot + open mutation state.
 */
import {
  TeamSourceCollectionStorageActionsPanel,
  type TeamSourceCollectionStorageAction,
} from "../TeamSourceCollectionStorageActionsPanel";
import {
  sourceCollectionStorageTargetLabel,
  type SourceCollectionStorageArtifacts,
  type SourceCollectionStorageOpenTarget,
} from "./source-collection/presentationModel";

const DETAIL_TARGETS: SourceCollectionStorageOpenTarget[] = [
  "search_plan",
  "search_events",
  "records",
  "candidates",
  "candidate_store",
];

export type TeamSourceCollectionStorageActionsInjectProps = {
  lang: "zh" | "en";
  artifacts: SourceCollectionStorageArtifacts | null | undefined;
  runId: string;
  pending: boolean;
  openedPath?: string;
  errorMessage?: string;
  onOpenTarget: (target: SourceCollectionStorageOpenTarget) => void;
};

export function TeamSourceCollectionStorageActionsInject({
  lang,
  artifacts,
  runId,
  pending,
  openedPath = "",
  errorMessage = "",
  onOpenTarget,
}: TeamSourceCollectionStorageActionsInjectProps) {
  if (!artifacts || !runId) {
    return null;
  }

  const primaryAction: TeamSourceCollectionStorageAction = {
    target: "run_directory",
    label: sourceCollectionStorageTargetLabel("run_directory", lang),
  };
  const detailActions: TeamSourceCollectionStorageAction[] = DETAIL_TARGETS.map((target) => ({
    target,
    label: sourceCollectionStorageTargetLabel(target, lang),
  }));

  return (
    <TeamSourceCollectionStorageActionsPanel
      lang={lang}
      runDirectory={artifacts.runDirectory}
      primaryAction={primaryAction}
      detailActions={detailActions}
      pending={pending}
      openedPath={openedPath}
      errorMessage={errorMessage}
      onOpenTarget={(target) => onOpenTarget(target as SourceCollectionStorageOpenTarget)}
    />
  );
}
