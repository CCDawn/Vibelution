/**
 * SC inject claim: selected-source detail workspace ownership.
 */
import {
  TeamSourceCollectionSelectedSourceWorkspacePanel,
  type TeamSourceCollectionSelectedSourceWorkspacePanelProps,
} from "../TeamSourceCollectionSelectedSourceWorkspacePanel";

export type TeamSourceCollectionSelectedSourceInjectProps = TeamSourceCollectionSelectedSourceWorkspacePanelProps;

export function TeamSourceCollectionSelectedSourceInject(props: TeamSourceCollectionSelectedSourceInjectProps) {
  return <TeamSourceCollectionSelectedSourceWorkspacePanel {...props} />;
}
