const scope = "vui-components-conversation-terminal-tool-detail";

const styles = {
  root:
    `${scope} root grid min-w-0 overflow-hidden rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)]`,
  header:
    `${scope} header border-b border-[var(--vui-border-subtle)] px-3 py-1.5 [font-size:var(--vui-font-xs)] font-medium text-[var(--fg-tertiary)]`,
  command:
    `${scope} command m-0 min-w-0 max-w-full overflow-auto whitespace-pre-wrap bg-[var(--vui-surface-raised)] px-3 py-2 font-[var(--font-mono)] [font-size:var(--vui-font-sm)] leading-[1.6] text-[var(--fg-primary)] [overflow-wrap:anywhere]`,
  output:
    `${scope} output m-0 min-w-0 max-w-full overflow-auto whitespace-pre-wrap border-t border-[var(--vui-border-subtle)] bg-transparent px-3 py-2 font-[var(--font-mono)] [font-size:var(--vui-font-sm)] leading-[1.6] text-[var(--fg-secondary)] [overflow-wrap:anywhere]`,
  error:
    `${scope} error m-0 min-w-0 max-w-full overflow-auto whitespace-pre-wrap border-t border-[color-mix(in_srgb,var(--state-error)_28%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--state-error)_4%,var(--vui-surface-panel))] px-3 py-2 font-[var(--font-mono)] [font-size:var(--vui-font-sm)] leading-[1.6] text-[var(--state-error)] [overflow-wrap:anywhere]`,
};

export default styles;
