import { createContext } from "react";

export type ConversationComposerSecondaryAction = {
  id: "queue" | "interrupt";
  label: string;
  disabled: boolean;
  hint?: string;
  onSelect: () => void;
};

/** Shared delivery actions consumed by a host-owned plus menu in this composer. */
export const ConversationComposerActionsContext = createContext<readonly ConversationComposerSecondaryAction[]>([]);
