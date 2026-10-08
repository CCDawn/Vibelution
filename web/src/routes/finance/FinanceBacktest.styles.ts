import evaluationStyles from "./FinanceEvaluation.styles";

export default {
  ...evaluationStyles,
  modeRow: `${evaluationStyles.row} px-3 pt-3`,
  modeSelect: "w-44",
} as const;
