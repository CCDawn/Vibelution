/**
 * SC inject claim: active-stage workspace body ownership.
 * Keeps TeamsRoute as mutation/query orchestration; panel implementation stays here.
 */
import {
  TeamSourceCollectionActiveStageWorkspacePanel,
  type TeamSourceCollectionActiveStageWorkspacePanelProps,
} from "../TeamSourceCollectionActiveStageWorkspacePanel";

export type TeamSourceCollectionActiveStageInjectProps = TeamSourceCollectionActiveStageWorkspacePanelProps;

export function TeamSourceCollectionActiveStageInject(props: TeamSourceCollectionActiveStageInjectProps) {
  return <TeamSourceCollectionActiveStageWorkspacePanel {...props} />;
}
