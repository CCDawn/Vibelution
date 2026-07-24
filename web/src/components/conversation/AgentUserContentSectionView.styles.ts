import { vuiStateUserBubbleClass } from "../../design/vuiSurfaceRecipes";

const styles = {
  // surface-role: message-bubble — fixed cool wash on panel; not a structural board
  userMessageBody:
    `vui-components-conversationview userMessageBody min-w-0 [font-size:var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)] w-fit max-w-[min(100%,68ch)] justify-self-end whitespace-pre-wrap ${vuiStateUserBubbleClass} px-2.5 py-1.5 text-left text-[var(--fg-primary)] shadow-none [overflow-wrap:anywhere] [&_.markdownBody]:max-w-[min(100%,68ch)] [&_.markdownBody]:whitespace-normal [&_.markdownBody]:break-words [&_.markdownBody]:[overflow-wrap:anywhere] [&_.inlineLink]:break-words [&_.inlineLink]:[overflow-wrap:anywhere]`,
} as const;

export default styles;
