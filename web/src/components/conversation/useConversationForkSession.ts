import { useCallback, useState } from "react";

import type { ConversationMessage } from "../../api/types";
import type { ConversationForkScope } from "./ConversationForkSessionDialog";

export type UseConversationForkSessionInput = {
  onForkSessionFromNode?: (
    message: ConversationMessage,
    scope: ConversationForkScope,
  ) => Promise<void> | void;
};

export type UseConversationForkSessionResult = {
  forkDialogMessage: ConversationMessage | null;
  forkScope: ConversationForkScope;
  forkPending: boolean;
  setForkScope: (scope: ConversationForkScope) => void;
  openForkDialog: (message: ConversationMessage) => void;
  closeForkDialog: () => void;
  confirmForkSession: () => void;
};

/**
 * Branch fork exit: dialog target message, copy scope, and pending submit.
 * Extracted from ConversationView. The route still executes the API call;
 * the shell still mounts ConversationForkSessionDialog.
 */
export function useConversationForkSession({
  onForkSessionFromNode,
}: UseConversationForkSessionInput): UseConversationForkSessionResult {
  const [forkDialogMessage, setForkDialogMessage] = useState<ConversationMessage | null>(null);
  const [forkScope, setForkScope] = useState<ConversationForkScope>("visible_path");
  const [forkPending, setForkPending] = useState(false);

  const openForkDialog = useCallback((message: ConversationMessage) => {
    setForkScope("visible_path");
    setForkDialogMessage(message);
  }, []);

  const closeForkDialog = useCallback(() => {
    setForkDialogMessage(null);
  }, []);

  const confirmForkSession = useCallback(() => {
    const message = forkDialogMessage;
    if (!message || !onForkSessionFromNode || forkPending) {
      return;
    }
    setForkPending(true);
    void Promise.resolve(onForkSessionFromNode(message, forkScope))
      .then(() => setForkDialogMessage(null))
      .catch(() => undefined)
      .finally(() => setForkPending(false));
  }, [forkDialogMessage, forkPending, forkScope, onForkSessionFromNode]);

  return {
    forkDialogMessage,
    forkScope,
    forkPending,
    setForkScope,
    openForkDialog,
    closeForkDialog,
    confirmForkSession,
  };
}
