/**
 * SC inject claim: memory / ingestion workspace body ownership.
 */
import {
  TeamSourceCollectionMemoryWorkspacePanel,
  type TeamSourceCollectionMemoryWorkspacePanelProps,
} from "../TeamSourceCollectionMemoryWorkspacePanel";

export type TeamSourceCollectionMemoryInjectProps = TeamSourceCollectionMemoryWorkspacePanelProps;

export function TeamSourceCollectionMemoryInject(props: TeamSourceCollectionMemoryInjectProps) {
  return <TeamSourceCollectionMemoryWorkspacePanel {...props} />;
}
