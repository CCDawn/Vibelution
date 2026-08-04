/**
 * SC inject claim: graph workspace body ownership.
 */
import {
  TeamSourceCollectionGraphWorkspacePanel,
  type TeamSourceCollectionGraphWorkspacePanelProps,
} from "../TeamSourceCollectionGraphWorkspacePanel";

export type TeamSourceCollectionGraphInjectProps = TeamSourceCollectionGraphWorkspacePanelProps;

export function TeamSourceCollectionGraphInject(props: TeamSourceCollectionGraphInjectProps) {
  return <TeamSourceCollectionGraphWorkspacePanel {...props} />;
}
