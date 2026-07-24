import {
  vuiStateCoolInfoClass,
  vuiWorkspaceFillClass,
} from "../../design/vuiSurfaceRecipes";

const styles = {
  cliAgentRunPanel:
    "vui-routes-chatcodingroute cliAgentRunPanel min-w-0 rounded-[var(--radius-panel)] border border-[color-mix(in_srgb,var(--accent-cool)_28%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_8%,transparent)] p-2 text-[var(--accent-cool)] shadow-none",
  cliAgentRunPanelHidden:
    "vui-routes-chatcodingroute cliAgentRunPanelHidden min-w-0 rounded-[var(--radius-panel)] border border-[color-mix(in_srgb,var(--accent-cool)_28%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_8%,transparent)] p-2 text-[var(--accent-cool)] shadow-none hidden",
  cliAgentTerminalAction:
    `vui-routes-chatcodingroute cliAgentTerminalAction min-w-0 flex flex-wrap items-center gap-1.5 ${vuiStateCoolInfoClass}`,
  cliAgentTerminalCommand:
    `vui-routes-chatcodingroute cliAgentTerminalCommand min-w-0 overflow-hidden ${vuiStateCoolInfoClass} !grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-2`,
  cliAgentTerminalCommandText:
    "vui-routes-chatcodingroute cliAgentTerminalCommandText min-w-0 max-w-full break-words [overflow-wrap:anywhere] text-[var(--fg-secondary)]",
  cliAgentTerminalFrame:
    `vui-routes-chatcodingroute cliAgentTerminalFrame min-w-0 ${vuiStateCoolInfoClass}`,
  cliAgentTerminalOutput:
    `vui-routes-chatcodingroute cliAgentTerminalOutput min-w-0 ${vuiStateCoolInfoClass}`,
  cliAgentTerminalOutputShell: `vui-routes-chatcodingroute cliAgentTerminalOutputShell min-w-0 grid h-full min-h-0 content-start overflow-hidden ${vuiWorkspaceFillClass} text-[var(--fg-primary)] ${vuiStateCoolInfoClass} bg-[var(--bg-canvas)]`,
  cliAgentTerminalOverlay:
    `vui-routes-chatcodingroute cliAgentTerminalOverlay min-w-0 ${vuiStateCoolInfoClass}`,
  cliAgentTerminalStatus:
    `vui-routes-chatcodingroute cliAgentTerminalStatus min-w-0 ${vuiStateCoolInfoClass}`,
} as const;

export default styles;
