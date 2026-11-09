const styles = {
  trigger: "vui-app-appshell connectionNoticeTrigger !h-7 !min-h-7 !px-1.5 !text-vui-xs",
  triggerContent:
    "vui-app-appshell connectionNoticeTriggerContent flex min-w-0 items-center gap-0.5 whitespace-nowrap text-[var(--state-warning)]",
  panel:
    "vui-app-appshell connectionNoticePanel z-[95] w-[min(340px,calc(100vw-20px))] border-[var(--border-strong)] bg-[var(--shell-panel)] p-0 shadow-[var(--vui-shadow-soft)]",
  panelBody: "vui-app-appshell connectionNoticePanelBody grid min-w-0 gap-1.5 p-3",
  panelTitle: "text-vui-xs font-semibold text-[var(--fg-primary)]",
  paragraph: "block text-vui-xs text-[var(--fg-secondary)]",
  actions: "flex flex-wrap items-center gap-2 pt-0.5",
};
export default styles;
