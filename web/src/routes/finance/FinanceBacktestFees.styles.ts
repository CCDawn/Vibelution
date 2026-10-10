import backtestStyles from "./FinanceAIBacktest.styles";

// This fee surface owns its semantic style map while reusing the backtest
// geometry and source-link tokens shared with the adjacent dividend ledger.
export default {
  panel: backtestStyles.dividendDetails,
  row: backtestStyles.row,
  note: backtestStyles.note,
  table: backtestStyles.table,
  sourceLink: backtestStyles.dividendLink,
} as const;
