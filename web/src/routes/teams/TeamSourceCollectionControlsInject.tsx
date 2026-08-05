/**
 * SC inject claim: controls / side-rail workspace body ownership.
 * Runtime panel is lazy-packed (teamLazyPanels).
 */
import type { TeamSourceCollectionControlsWorkspacePanelProps } from "../TeamSourceCollectionControlsWorkspacePanel";
import { TeamSourceCollectionControlsWorkspacePanel } from "./teamLazyPanels";

export type TeamSourceCollectionControlsInjectProps = TeamSourceCollectionControlsWorkspacePanelProps;

export function TeamSourceCollectionControlsInject(props: TeamSourceCollectionControlsInjectProps) {
  return <TeamSourceCollectionControlsWorkspacePanel {...props} />;
}
