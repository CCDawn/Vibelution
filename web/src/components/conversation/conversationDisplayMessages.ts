import type { ConversationMessage } from "../../api/types";
import { projectConversationMessageFromTurnItemsV2 } from "../../routes/chatTurnProtocol";
import {
  isHotRestartResumeMessage,
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
    .filter((message) => !isRecoverySupersededPartial(message))
    // The resume resubmit re-journals the user text as a system-authored row
    // (kind=hot_restart_resume); it must not duplicate the original user row.
    .filter((message) => !isHotRestartResumeMessage(message));
}
