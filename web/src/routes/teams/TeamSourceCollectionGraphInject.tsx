/**
 * SC inject claim: graph workspace body ownership.
 * Runtime panel is lazy-packed (teamLazyPanels).
 */
import type { TeamSourceCollectionGraphWorkspacePanelProps } from "../TeamSourceCollectionGraphWorkspacePanel";
import { TeamSourceCollectionGraphWorkspacePanel } from "./teamLazyPanels";

export type TeamSourceCollectionGraphInjectProps = TeamSourceCollectionGraphWorkspacePanelProps;

export function TeamSourceCollectionGraphInject(props: TeamSourceCollectionGraphInjectProps) {
  return <TeamSourceCollectionGraphWorkspacePanel {...props} />;
}
