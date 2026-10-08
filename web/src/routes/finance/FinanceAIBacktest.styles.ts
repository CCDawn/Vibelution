import evaluationStyles from "./FinanceEvaluation.styles";

export default {
  ...evaluationStyles,
  frequency: "w-32",
  progress: "h-1 w-full",
  reason: "block max-w-lg break-words text-xs",
} as const;
