import evaluationStyles from "./FinanceEvaluation.styles";

export default {
  ...evaluationStyles,
  frequency: "w-32",
  scopeSelect: "w-32",
  assetList: "flex min-w-0 flex-wrap items-center gap-2",
  assetChip: "inline-flex min-w-0 items-center gap-1 rounded-md border border-vui-border-subtle px-2 py-1",
  history: "flex min-w-0 flex-wrap items-center gap-2 [&_button]:whitespace-nowrap",
  comparisonShell: "flex min-w-0 flex-col gap-2",
  comparisonSelection: "flex min-w-0 flex-wrap items-center gap-2",
  comparisonResult: "flex min-w-0 flex-col gap-2",
  comparisonTable: "[&_[role=columnheader]]:whitespace-nowrap",
  comparisonReasons: "flex min-w-0 flex-col gap-1",
  progress: "h-1 w-full",
  reason: "block max-w-lg break-words text-xs",
} as const;
