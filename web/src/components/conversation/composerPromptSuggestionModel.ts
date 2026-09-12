export type ComposerPromptSuggestionRequestInput = {
  enabled: boolean;
  sessionId: string;
  busy: boolean;
  draft: string;
  hasConversation: boolean;
  issued: boolean;
};

/**
 * Mirrors the Claude Code lifecycle: exactly one suggestion attempt per turn.
 * `issued` is reset by the hook when a new turn starts (busy goes true).
 */
export function shouldRequestComposerPromptSuggestion(
  input: ComposerPromptSuggestionRequestInput,
): boolean {
  return input.enabled
    && Boolean(input.sessionId)
    && !input.busy
    && input.draft === ""
    && input.hasConversation
    && !input.issued;
}

export type ComposerExampleRequestInput = {
  enabled: boolean;
  sessionId: string;
  hasConversation: boolean;
};

/** Starter prompts only matter for a thread that has no user turn yet. */
export function shouldLoadComposerExample(input: ComposerExampleRequestInput): boolean {
  return input.enabled && Boolean(input.sessionId) && !input.hasConversation;
}

export type ComposerGhostInput = {
  suggestion: string;
  draft: string;
  busy: boolean;
};

export function resolveComposerGhost(input: ComposerGhostInput): string {
  if (input.busy || input.draft !== "") {
    return "";
  }
  return input.suggestion.trim();
}

export type ComposerPlaceholderInput = {
  ghost: string;
  exampleCommand: string;
  hasConversation: boolean;
  lang: "zh" | "en";
  fallback: string;
};

/**
 * The ghost rides on the native placeholder: an empty textarea already renders
 * it in the muted placeholder color, and there is no overlay text to misalign.
 */
export function resolveComposerPlaceholder(input: ComposerPlaceholderInput): string {
  if (input.ghost) {
    return input.lang === "zh" ? `${input.ghost}（Tab 补全）` : `${input.ghost} (Tab to complete)`;
  }
  if (!input.hasConversation && input.exampleCommand) {
    return input.lang === "zh" ? `试试 “${input.exampleCommand}”` : `Try “${input.exampleCommand}”`;
  }
  return input.fallback;
}

export function shouldAcceptComposerGhost(input: {
  ghost: string;
  key: string;
  shiftKey: boolean;
  ctrlKey: boolean;
  metaKey: boolean;
  altKey: boolean;
}): boolean {
  if (!input.ghost || input.shiftKey || input.ctrlKey || input.metaKey || input.altKey) {
    return false;
  }
  return input.key === "Tab" || input.key === "ArrowRight";
}
