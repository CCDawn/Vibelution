import { useCallback, useEffect, useRef, useState } from "react";

import {
  fetchSessionComposerExample,
  fetchSessionPromptSuggestion,
  isFetchAbortError,
} from "../../api/chat";
import {
  shouldLoadComposerExample,
  shouldRequestComposerPromptSuggestion,
} from "./composerPromptSuggestionModel";

export type ComposerPromptSuggestionInput = {
  sessionId: string;
  enabled: boolean;
  busy: boolean;
  draft: string;
  hasConversation: boolean;
};

export type ComposerPromptSuggestionState = {
  ghost: string;
  exampleCommand: string;
  acceptGhost: () => void;
  dismissGhost: () => void;
};

/**
 * One suggestion attempt per turn: after a reply completes we ask the backend
 * for the cached suggestion of that turn; starting to type dismisses it and no
 * new attempt happens until the next turn starts. A local dismiss (Escape)
 * also stays dismissed for the turn.
 */
export function useComposerPromptSuggestion(
  input: ComposerPromptSuggestionInput,
  onAccept: (suggestion: string) => void,
): ComposerPromptSuggestionState {
  const { sessionId, enabled, busy, draft, hasConversation } = input;
  const [suggestion, setSuggestion] = useState("");
  const [dismissed, setDismissed] = useState(false);
  const [exampleCommand, setExampleCommand] = useState("");
  const issuedRef = useRef(false);

  useEffect(() => {
    issuedRef.current = false;
    setSuggestion("");
    setDismissed(false);
    setExampleCommand("");
  }, [sessionId]);

  useEffect(() => {
    if (busy) {
      issuedRef.current = false;
      setSuggestion("");
      setDismissed(false);
      return;
    }
    if (draft !== "") {
      // Typing dismisses the current suggestion for the rest of the turn.
      setSuggestion("");
      return;
    }
    if (!shouldRequestComposerPromptSuggestion({
      enabled,
      sessionId,
      busy,
      draft,
      hasConversation,
      issued: issuedRef.current,
    })) {
      return;
    }
    issuedRef.current = true;
    const controller = new AbortController();
    fetchSessionPromptSuggestion(sessionId, { signal: controller.signal })
      .then((response) => {
        setSuggestion(String(response?.suggestion ?? ""));
      })
      .catch((error) => {
        if (!isFetchAbortError(error)) {
          setSuggestion("");
        }
      });
    return () => controller.abort();
  }, [busy, draft, enabled, hasConversation, sessionId]);

  useEffect(() => {
    if (!shouldLoadComposerExample({ enabled, sessionId, hasConversation })) {
      setExampleCommand("");
      return;
    }
    const controller = new AbortController();
    fetchSessionComposerExample(sessionId, { signal: controller.signal })
      .then((response) => {
        setExampleCommand(String(response?.command ?? "").trim());
      })
      .catch((error) => {
        if (!isFetchAbortError(error)) {
          setExampleCommand("");
        }
      });
    return () => controller.abort();
  }, [enabled, hasConversation, sessionId]);

  const acceptGhost = useCallback(() => {
    if (!suggestion || dismissed) {
      return;
    }
    setSuggestion("");
    onAccept(suggestion);
  }, [dismissed, onAccept, suggestion]);

  const dismissGhost = useCallback(() => {
    setDismissed(true);
    setSuggestion("");
  }, []);

  const ghost = dismissed || draft !== "" || busy ? "" : suggestion.trim();
  return { ghost, exampleCommand, acceptGhost, dismissGhost };
}
