/**
 * SC inject claim: selected-source detail workspace ownership.
 * Runtime panel is lazy-packed (teamLazyPanels).
 */
import type { TeamSourceCollectionSelectedSourceWorkspacePanelProps } from "../TeamSourceCollectionSelectedSourceWorkspacePanel";
import { TeamSourceCollectionSelectedSourceWorkspacePanel } from "./teamLazyPanels";

export type TeamSourceCollectionSelectedSourceInjectProps = TeamSourceCollectionSelectedSourceWorkspacePanelProps;

export function TeamSourceCollectionSelectedSourceInject(props: TeamSourceCollectionSelectedSourceInjectProps) {
  return <TeamSourceCollectionSelectedSourceWorkspacePanel {...props} />;
}
