/**
 * SC inject claim: memory / ingestion workspace body ownership.
 * Runtime panel is lazy-packed (teamLazyPanels).
 */
import type { TeamSourceCollectionMemoryWorkspacePanelProps } from "../TeamSourceCollectionMemoryWorkspacePanel";
import { TeamSourceCollectionMemoryWorkspacePanel } from "./teamLazyPanels";

export type TeamSourceCollectionMemoryInjectProps = TeamSourceCollectionMemoryWorkspacePanelProps;

export function TeamSourceCollectionMemoryInject(props: TeamSourceCollectionMemoryInjectProps) {
  return <TeamSourceCollectionMemoryWorkspacePanel {...props} />;
}
