import type { ConversationMessage } from "../../api/types";

export type TurnAvatarResolution = {
  imageUrl?: string;
  fallback: string;
};

export type TurnAvatarContent =
  | TurnAvatarResolution
  | { icon: "groupTranscript" };

export function userAvatarSymbol(preset: string | undefined, label: string) {
  const normalized = String(preset ?? "").trim().toLowerCase();
  if (normalized === "spark") {
    return "*";
  }
  if (normalized === "codex") {
    return "C";
  }
  if (normalized === "minimal") {
    return ".";
  }
  return label.trim().slice(0, 1).toUpperCase() || "U";
}

export function resolveMessageTurnAvatar(
  message: ConversationMessage,
  options: {
    resolveTurnAvatar?: (message: ConversationMessage) => TurnAvatarResolution | undefined;
    assistantAvatarImageUrl?: string;
    assistantAvatarFallback?: string;
    assistantLabel: string;
    userAvatarImageUrl?: string;
    userAvatarLabel: string;
    agentInboxMessage: boolean;
    groupTranscriptMessage: boolean;
  },
): TurnAvatarContent {
  if (options.groupTranscriptMessage) {
    return { icon: "groupTranscript" };
  }
  if (options.agentInboxMessage) {
    const resolved = options.resolveTurnAvatar?.(message);
    if (resolved) {
      return resolved;
    }
    return { fallback: "?" };
  }
  if (message.role === "assistant") {
    return {
      imageUrl: options.assistantAvatarImageUrl,
      fallback: options.assistantAvatarFallback || options.assistantLabel.trim().slice(0, 2) || "AI",
    };
  }
  return {
    imageUrl: options.userAvatarImageUrl,
    fallback: options.userAvatarLabel,
  };
}
