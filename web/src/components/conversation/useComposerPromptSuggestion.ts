import { useCallback, useEffect, useRef, useState } from "react";

import {
  fetchSessionComposerExample,
  fetchSessionPromptSuggestion,
  isFetchAbortError,
} from "../../api/chat";
import {
  resolveComposerStarters,
  shouldLoadComposerExample,
  shouldRequestComposerPromptSuggestion,
  type ComposerStarter,
} from "./composerPromptSuggestionModel";

export type ComposerPromptSuggestionInput = {
  sessionId: string;
  /** Per-session AI ghost suggestion toggle; deterministic starters ignore it. */
  suggestionEnabled: boolean;
  /** Starters only need a usable composer, not the AI suggestion opt-in. */
  starterEnabled: boolean;
  busy: boolean;
  draft: string;
  hasConversation: boolean;
};

export type ComposerPromptSuggestionState = {
  ghost: string;
  exampleCommand: string;
  starters: ComposerStarter[];
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
  const { sessionId, suggestionEnabled, starterEnabled, busy, draft, hasConversation } = input;
  const [suggestion, setSuggestion] = useState("");
  const [dismissed, setDismissed] = useState(false);
  const [exampleCommand, setExampleCommand] = useState("");
  const [starters, setStarters] = useState<ComposerStarter[]>([]);
  const issuedRef = useRef(false);

  useEffect(() => {
    issuedRef.current = false;
    setSuggestion("");
    setDismissed(false);
    setExampleCommand("");
    setStarters([]);
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
      suggestionEnabled,
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
  }, [busy, draft, hasConversation, sessionId, suggestionEnabled]);

  useEffect(() => {
    if (!shouldLoadComposerExample({ enabled: starterEnabled, sessionId, hasConversation })) {
      setExampleCommand("");
      setStarters([]);
      return;
    }
    const controller = new AbortController();
    fetchSessionComposerExample(sessionId, { signal: controller.signal })
      .then((response) => {
        const resolved = resolveComposerStarters(response ?? {});
        setStarters(resolved);
        setExampleCommand(resolved[0]?.command ?? "");
      })
      .catch((error) => {
        if (!isFetchAbortError(error)) {
          setExampleCommand("");
          setStarters([]);
        }
      });
    return () => controller.abort();
  }, [hasConversation, sessionId, starterEnabled]);

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
  return { ghost, exampleCommand, starters, acceptGhost, dismissGhost };
}
