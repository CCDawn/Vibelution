import {
  vuiStateCoolInfoClass,
} from "../../design/vuiSurfaceRecipes";

const styles = {
  agentMention:
    `vui-routes-chatcodingroute agentMention min-w-0 ${vuiStateCoolInfoClass}`,
  groupBubbleBody:
    "vui-routes-chatcodingroute groupBubbleBody min-w-0 [font-size:var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)]",
  groupBubbleBodyCollapsed:
    "vui-routes-chatcodingroute groupBubbleBodyCollapsed min-w-0 [font-size:var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)] hidden",
  groupBubbleToggle: "vui-routes-chatcodingroute groupBubbleToggle min-w-0",
} as const;

export default styles;
