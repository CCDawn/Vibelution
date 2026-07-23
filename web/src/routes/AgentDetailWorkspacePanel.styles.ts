const styles = {
  detailPanel:
    "h-full min-w-0 min-h-0 [grid-template-rows:auto_minmax(0,_1fr)] [overflow:hidden] max-[860px]:[min-height:420px] max-[860px]:[max-height:none] max-[860px]:[overflow:auto]",
  detailScroll:
    "min-h-0 min-w-0 [overflow:auto] [overscroll-behavior:contain]",
} as const;

export default styles;
