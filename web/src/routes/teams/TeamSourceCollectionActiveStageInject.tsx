/**
 * SC inject claim: active-stage workspace body ownership.
 * Keeps TeamsRoute as mutation/query orchestration; panel implementation stays here.
 * Extraction recovery bag is assembled via buildSourceCollectionExtractionRecoveryBag.
 *
 * Runtime panel comes from teamLazyPanels so the SC pack stays out of the eager TeamsRoute graph.
 */
import type { TeamSourceCollectionActiveStageWorkspacePanelProps } from "../TeamSourceCollectionActiveStageWorkspacePanel";
import { TeamSourceCollectionActiveStageWorkspacePanel } from "./teamLazyPanels";
import {
  buildSourceCollectionExtractionRecoveryBag,
  type SourceCollectionExtractionRecoveryBag,
} from "./source-collection/extractionRecoveryBag";

export type TeamSourceCollectionActiveStageInjectProps = Omit<
  TeamSourceCollectionActiveStageWorkspacePanelProps,
  "extractionRecovery"
> & {
  extractionRecovery?: SourceCollectionExtractionRecoveryBag | null;
};

export type { SourceCollectionExtractionRecoveryBag };
export { buildSourceCollectionExtractionRecoveryBag };

export function TeamSourceCollectionActiveStageInject({
  extractionRecovery,
  ...panelProps
}: TeamSourceCollectionActiveStageInjectProps) {
  return (
    <TeamSourceCollectionActiveStageWorkspacePanel
      {...panelProps}
      extractionRecovery={
        extractionRecovery
          ? buildSourceCollectionExtractionRecoveryBag(extractionRecovery)
          : undefined
      }
    />
  );
}
