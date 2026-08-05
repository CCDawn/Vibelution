/**
 * SC inject claim: conversation / raw-records workspace ownership.
 * Runtime panel is lazy-packed (teamLazyPanels).
 */
import type { TeamSourceCollectionConversationWorkspacePanelProps } from "../TeamSourceCollectionConversationWorkspacePanel";
import { TeamSourceCollectionConversationWorkspacePanel } from "./teamLazyPanels";

export type TeamSourceCollectionConversationInjectProps = TeamSourceCollectionConversationWorkspacePanelProps;

export function TeamSourceCollectionConversationInject(props: TeamSourceCollectionConversationInjectProps) {
  return <TeamSourceCollectionConversationWorkspacePanel {...props} />;
}
