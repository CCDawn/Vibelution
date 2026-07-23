const styles = {
  // Seamless workbench: no inter-card gutter; columns touch via hairline only.
  workspace:
    "flex h-full min-h-0 w-full min-w-0 overflow-hidden rounded-[var(--radius-panel)] border border-[color-mix(in_srgb,var(--vui-border-subtle)_80%,transparent)] max-[860px]:flex-col max-[860px]:[grid-template-columns:1fr] max-[860px]:[overflow:auto]",
  directory:
    "grid h-full min-h-0 min-w-0 shrink-0 [grid-template-rows:auto_minmax(0,1fr)] overflow-hidden border-r border-[color-mix(in_srgb,var(--vui-border-subtle)_80%,transparent)] max-[860px]:min-h-[320px] max-[860px]:w-full! max-[860px]:max-w-none! max-[860px]:border-r-0 max-[860px]:border-b",
  directoryFilter:
    "min-h-0 min-w-0 overflow-hidden border-b border-[color-mix(in_srgb,var(--vui-border-subtle)_72%,transparent)] [&_[data-vui-product=agent-workspace-panel]]:!rounded-none [&_[data-vui-product=agent-workspace-panel]]:!border-0 [&_[data-vui-product=agent-workspace-panel]]:!bg-transparent [&_[data-vui-product=agent-workspace-panel]]:!p-2 [&_[data-vui-product=agent-workspace-panel]]:!gap-1.5 [&_[data-vui-product=agent-workspace-panel]]:!shadow-none",
  directoryList:
    "min-h-0 min-w-0 overflow-hidden [&_[data-vui-product=agent-workspace-panel]]:h-full [&_[data-vui-product=agent-workspace-panel]]:!rounded-none [&_[data-vui-product=agent-workspace-panel]]:!border-0 [&_[data-vui-product=agent-workspace-panel]]:!bg-transparent [&_[data-vui-product=agent-workspace-panel]]:!p-2 [&_[data-vui-product=agent-workspace-panel]]:!gap-1.5 [&_[data-vui-product=agent-workspace-panel]]:!shadow-none",
  main:
    "grid h-full min-h-0 min-w-0 flex-1 overflow-hidden [&_[data-vui-product=agent-workspace-panel]]:h-full [&_[data-vui-product=agent-workspace-panel]]:!rounded-none [&_[data-vui-product=agent-workspace-panel]]:!border-0 [&_[data-vui-product=agent-workspace-panel]]:!bg-transparent [&_[data-vui-product=agent-workspace-panel]]:!p-2 [&_[data-vui-product=agent-workspace-panel]]:!shadow-none",
  inspector:
    "grid h-full min-h-0 min-w-0 shrink-0 overflow-hidden border-l border-[color-mix(in_srgb,var(--vui-border-subtle)_80%,transparent)] max-[1040px]:hidden [&_[data-vui-product=agent-workspace-panel]]:h-full [&_[data-vui-product=agent-workspace-panel]]:!rounded-none [&_[data-vui-product=agent-workspace-panel]]:!border-0 [&_[data-vui-product=agent-workspace-panel]]:!bg-transparent [&_[data-vui-product=agent-workspace-panel]]:!p-2 [&_[data-vui-product=agent-workspace-panel]]:!shadow-none",
  resizeHandle:
    "relative z-20 h-full w-1.5 shrink-0 cursor-col-resize touch-none border-0 bg-transparent p-0 outline-none max-[860px]:hidden before:pointer-events-none before:absolute before:inset-y-0 before:left-1/2 before:w-px before:-translate-x-1/2 before:bg-transparent before:opacity-0 before:transition before:content-[''] hover:before:bg-[color-mix(in_srgb,var(--accent-cool)_42%,transparent)] hover:before:opacity-100 focus-visible:before:bg-[color-mix(in_srgb,var(--accent-cool)_42%,transparent)] focus-visible:before:opacity-100 after:absolute after:inset-y-0 after:left-1/2 after:w-3 after:-translate-x-1/2 after:content-['']",
  resizeHandleActive:
    "before:bg-[color-mix(in_srgb,var(--accent-cool)_56%,transparent)] before:opacity-100",
  // Layout-contract aliases (legacy class names still referenced by tests).
  workspaceWithInspector:
    "flex h-full min-h-0 w-full min-w-0 overflow-hidden rounded-[var(--radius-panel)] border border-[color-mix(in_srgb,var(--vui-border-subtle)_80%,transparent)]",
} as const;

export default styles;
