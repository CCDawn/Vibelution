const styles={
  root:"z-20 h-[var(--shell-topbar-height)] min-h-[var(--shell-topbar-height)] gap-1 !border-0 !bg-vui-surface-rail px-2 [-webkit-app-region:no-drag]",
  desktop:"!pr-[max(var(--shell-window-control-inset),calc(100vw_-_env(titlebar-area-x,0px)_-_env(titlebar-area-width,calc(100vw_-_var(--shell-window-control-inset)))))]",
  menu:"min-[701px]:!hidden",
  icon:"shrink-0 text-vui-fg-secondary",
  brand:"text-vui-sm font-semibold max-[520px]:hidden",
  subtitle:"border-l border-vui-border-subtle pl-2.5 text-vui-micro-11 text-vui-fg-tertiary max-[700px]:hidden",
  drag:"min-w-6 flex-1 self-stretch [-webkit-app-region:drag] max-[520px]:min-w-0",
} as const;
export default styles;
