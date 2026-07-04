const styles = {
  cliAgentRunPanel:
    "vui-routes-chatcodingroute cliAgentRunPanel min-w-0 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-glass)] shadow-[var(--vui-shadow-hairline)] p-2 border-[color-mix(in_srgb,var(--accent-cool)_28%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_8%,transparent)] text-[var(--accent-cool)]",
  cliAgentRunPanelHidden:
    "vui-routes-chatcodingroute cliAgentRunPanelHidden min-w-0 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-glass)] shadow-[var(--vui-shadow-hairline)] p-2 hidden border-[color-mix(in_srgb,var(--accent-cool)_28%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_8%,transparent)] text-[var(--accent-cool)] hidden",
  cliAgentTerminalAction:
    "vui-routes-chatcodingroute cliAgentTerminalAction min-w-0 flex flex-wrap items-center gap-1.5 border-[color-mix(in_srgb,var(--accent-cool)_28%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_8%,transparent)] text-[var(--accent-cool)]",
  cliAgentTerminalCommand:
    "vui-routes-chatcodingroute cliAgentTerminalCommand min-w-0 border-[color-mix(in_srgb,var(--accent-cool)_28%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_8%,transparent)] text-[var(--accent-cool)] !grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-2",
  cliAgentTerminalFrame:
    "vui-routes-chatcodingroute cliAgentTerminalFrame min-w-0 border-[color-mix(in_srgb,var(--accent-cool)_28%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_8%,transparent)] text-[var(--accent-cool)]",
  cliAgentTerminalOutput:
    "vui-routes-chatcodingroute cliAgentTerminalOutput min-w-0 border-[color-mix(in_srgb,var(--accent-cool)_28%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_8%,transparent)] text-[var(--accent-cool)]",
  cliAgentTerminalOutputShell:
    "vui-routes-chatcodingroute cliAgentTerminalOutputShell min-w-0 grid h-full min-h-0 content-start overflow-hidden bg-[var(--surface-page)] text-[var(--fg-primary)] border-[color-mix(in_srgb,var(--accent-cool)_28%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_8%,transparent)] text-[var(--accent-cool)] bg-[var(--bg-canvas)]",
  cliAgentTerminalOverlay:
    "vui-routes-chatcodingroute cliAgentTerminalOverlay min-w-0 border-[color-mix(in_srgb,var(--accent-cool)_28%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_8%,transparent)] text-[var(--accent-cool)]",
  cliAgentTerminalStatus:
    "vui-routes-chatcodingroute cliAgentTerminalStatus min-w-0 border-[color-mix(in_srgb,var(--accent-cool)_28%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_8%,transparent)] text-[var(--accent-cool)]",
} as const;

export default styles;
