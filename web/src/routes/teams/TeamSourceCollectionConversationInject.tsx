/**
 * SC inject claim: conversation / raw-records workspace ownership.
 */
import {
  TeamSourceCollectionConversationWorkspacePanel,
  type TeamSourceCollectionConversationWorkspacePanelProps,
} from "../TeamSourceCollectionConversationWorkspacePanel";

export type TeamSourceCollectionConversationInjectProps = TeamSourceCollectionConversationWorkspacePanelProps;

export function TeamSourceCollectionConversationInject(props: TeamSourceCollectionConversationInjectProps) {
  return <TeamSourceCollectionConversationWorkspacePanel {...props} />;
}
