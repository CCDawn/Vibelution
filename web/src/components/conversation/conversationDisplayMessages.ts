import type { ConversationMessage } from "../../api/types";
import { projectConversationMessageFromTurnItemsV2 } from "../../routes/chatTurnProtocol";
import {
  isRuntimeNoticeMessage,
} from "./conversationMessagePredicates";
import { chronologicalConversationMessages } from "./conversationMessageOrder";

export function projectConversationDisplayMessages(messages: ConversationMessage[]) {
  const canonicalMessages = messages.map(projectConversationMessageFromTurnItemsV2);
  // Error de-duplication is item identity/revision based.  Never merge a
  // second synthetic message shape just to hide repeated status text.
  return chronologicalConversationMessages(canonicalMessages)
    .filter((message) => !isRuntimeNoticeMessage(message));
}
