/**
 * SC inject claim: controls / side-rail workspace body ownership.
 * Keeps TeamsRoute as mutation/query orchestration; panel implementation stays here.
 */
import {
  TeamSourceCollectionControlsWorkspacePanel,
  type TeamSourceCollectionControlsWorkspacePanelProps,
} from "../TeamSourceCollectionControlsWorkspacePanel";

export type TeamSourceCollectionControlsInjectProps = TeamSourceCollectionControlsWorkspacePanelProps;

export function TeamSourceCollectionControlsInject(props: TeamSourceCollectionControlsInjectProps) {
  return <TeamSourceCollectionControlsWorkspacePanel {...props} />;
}
