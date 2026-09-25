import type { ConversationMessage } from "../../api/types";
import { projectConversationMessageFromTurnItemsV2 } from "../../routes/chatTurnProtocol";
import {
  isRecoverySupersededPartial,
  isRuntimeNoticeMessage,
} from "./conversationMessagePredicates";
import { chronologicalConversationMessages } from "./conversationMessageOrder";

export function projectConversationDisplayMessages(messages: ConversationMessage[]) {
  const canonicalMessages = messages.map(projectConversationMessageFromTurnItemsV2);
  // Error de-duplication is item identity/revision based.  Never merge a
  // second synthetic message shape just to hide repeated status text.
  return chronologicalConversationMessages(canonicalMessages)
    .filter((message) => !isRuntimeNoticeMessage(message))
    // Superseded interrupted partials stay in the journal; they only leave the
    // display timeline once a recovery turn replaces them.
    .filter((message) => !isRecoverySupersededPartial(message));
}
