const styles={
  root:"z-20 h-12 min-h-12 gap-2.5 !border-0 border-b border-vui-border-subtle !bg-vui-surface-raised px-5 max-[700px]:px-2",
  desktop:"!pr-[max(138px,calc(100vw_-_env(titlebar-area-x,0px)_-_env(titlebar-area-width,calc(100vw_-_138px))))] [-webkit-app-region:no-drag]",
  menu:"!hidden max-[700px]:!inline-flex",
  icon:"shrink-0 text-vui-fg-secondary",
  brand:"text-vui-sm font-semibold",
  subtitle:"border-l border-vui-border-subtle pl-2.5 text-vui-micro-11 text-vui-fg-tertiary max-[700px]:hidden",
  drag:"min-w-6 flex-1 self-stretch [-webkit-app-region:drag]",
} as const;
export default styles;
