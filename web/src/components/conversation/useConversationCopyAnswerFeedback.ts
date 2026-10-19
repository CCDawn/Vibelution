import { useCallback, useEffect, useRef, useState } from "react";

/** Visible check-icon dwell after a successful answer copy. */
const COPY_ANSWER_FEEDBACK_MS = 1600;

export type UseConversationCopyAnswerFeedbackInput = {
  copyText: (text: string) => Promise<void>;
};

export type UseConversationCopyAnswerFeedbackResult = {
  copiedAnswerMessageId: string;
  handleCopyAnswer: (messageId: string, text: string) => void;
};

/**
 * Copy-answer button feedback: which message currently shows the check icon.
 * Extracted from ConversationView. Empty text is ignored; clipboard failure
 * is swallowed; a later copy resets the timer, and a stale timer clears the
 * id only when it still matches the message that started it.
 */
export function useConversationCopyAnswerFeedback({
  copyText,
}: UseConversationCopyAnswerFeedbackInput): UseConversationCopyAnswerFeedbackResult {
  const [copiedAnswerMessageId, setCopiedAnswerMessageId] = useState("");
  const copyAnswerFeedbackTimerRef = useRef<number | null>(null);

  useEffect(() => () => {
    if (copyAnswerFeedbackTimerRef.current !== null) {
      window.clearTimeout(copyAnswerFeedbackTimerRef.current);
    }
  }, []);

  const handleCopyAnswer = useCallback((messageId: string, text: string) => {
    const trimmed = text.trim();
    if (!trimmed) {
      return;
    }
    void copyText(trimmed).then(() => {
      setCopiedAnswerMessageId(messageId);
      if (copyAnswerFeedbackTimerRef.current !== null) {
        window.clearTimeout(copyAnswerFeedbackTimerRef.current);
      }
      copyAnswerFeedbackTimerRef.current = window.setTimeout(() => {
        copyAnswerFeedbackTimerRef.current = null;
        setCopiedAnswerMessageId((current) => (current === messageId ? "" : current));
      }, COPY_ANSWER_FEEDBACK_MS);
    }).catch(() => undefined);
  }, [copyText]);

  return {
    copiedAnswerMessageId,
    handleCopyAnswer,
  };
}
