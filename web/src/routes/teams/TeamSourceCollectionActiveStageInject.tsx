/**
 * SC inject claim: active-stage workspace body ownership.
 * Keeps TeamsRoute as mutation/query orchestration; panel implementation stays here.
 * Extraction recovery bag is assembled via buildSourceCollectionExtractionRecoveryBag.
 */
import {
  TeamSourceCollectionActiveStageWorkspacePanel,
  type TeamSourceCollectionActiveStageWorkspacePanelProps,
} from "../TeamSourceCollectionActiveStageWorkspacePanel";
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
