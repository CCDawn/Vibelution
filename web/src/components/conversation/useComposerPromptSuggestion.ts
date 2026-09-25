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
 * One shown suggestion per turn. An attempt that never appears (aborted
 * before the text arrives, or an empty result) can run again when the
 * composer is empty. Typing over a visible suggestion, or Escape, stays
 * dismissed until the next turn.
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
  const shownRef = useRef(false);

  useEffect(() => {
    issuedRef.current = false;
    shownRef.current = false;
    setSuggestion("");
    setDismissed(false);
    setExampleCommand("");
    setStarters([]);
  }, [sessionId]);

  useEffect(() => {
    if (busy) {
      issuedRef.current = false;
      shownRef.current = false;
      setSuggestion("");
      setDismissed(false);
      return;
    }
    if (draft !== "") {
      if (shownRef.current) {
        setDismissed(true);
      }
      setSuggestion("");
      return;
    }
    if (dismissed) {
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
    let revealed = false;
    fetchSessionPromptSuggestion(sessionId, { signal: controller.signal })
      .then((response) => {
        if (controller.signal.aborted) {
          return;
        }
        const text = String(response?.suggestion ?? "").trim();
        if (!text) {
          issuedRef.current = false;
          setSuggestion("");
          return;
        }
        revealed = true;
        shownRef.current = true;
        setSuggestion(text);
      })
      .catch((error) => {
        if (controller.signal.aborted || isFetchAbortError(error)) {
          return;
        }
        issuedRef.current = false;
        setSuggestion("");
      });
    return () => {
      controller.abort();
      if (!revealed && !shownRef.current) {
        issuedRef.current = false;
      }
    };
  }, [busy, dismissed, draft, hasConversation, sessionId, suggestionEnabled]);

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
