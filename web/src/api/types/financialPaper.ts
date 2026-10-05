export type PaperSide = "buy" | "sell";
export type PaperValuationStatus = "fresh" | "stale" | "unavailable";

export type PaperFeePolicy = {
  commissionRate: string;
  minimumCommissionYuan: string;
  sellStampDutyRate: string;
  transferFeeIncluded: boolean;
  description: string;
};

export type PaperPosition = {
  symbol: string;
  ticker: string;
  name: string;
  market: string;
  quantity: number;
  availableQuantity: number;
  frozenQuantity: number;
  averageCostYuan: string;
  costBasisYuan: string;
  markPriceYuan: string | null;
  marketValueYuan: string | null;
  unrealizedPnlYuan: string | null;
  valuationStatus: PaperValuationStatus;
  quoteTimestamp: string;
  quoteDate: string;
  quoteFetchedAt: string;
  source: string;
  sourceUrl: string;
};

export type PaperOrder = {
  orderId: string;
  clientOrderId: string;
  symbol: string;
  ticker: string;
  name: string;
  market: string;
  side: PaperSide;
  quantity: number;
  priceYuan: string;
  grossAmountYuan: string;
  commissionYuan: string;
  stampDutyYuan: string;
  totalFeeYuan: string;
  cashChangeYuan: string;
  realizedPnlYuan: string;
  reason: string;
  createdAt: string;
  beijingDate: string;
  quoteSource: string;
  quoteSourceUrl: string;
  quoteTimestamp: string;
  quoteDate: string;
  quoteFetchedAt: string;
  priceNotice: string;
};

export type PaperAccountSnapshot = {
  agentId: string;
  accountId: string;
  openedAt: string;
  initialCashYuan: string;
  cashYuan: string;
  marketValueYuan: string;
  equityYuan: string;
  realizedPnlYuan: string;
  unrealizedPnlYuan: string;
  totalPnlYuan: string;
  totalFeesYuan: string;
  valuationStatus: "fresh" | "partial";
  valuationNotice: string;
  positions: PaperPosition[];
  orders: PaperOrder[];
  ordersTotal: number;
  ordersLimit: number;
  ordersTruncated: boolean;
  feePolicy: PaperFeePolicy;
  tPlusOneRule: string;
  simulationOnly: true;
};

export type PaperReviewDay = {
  date: string;
  tradeCount: number;
  buyCount: number;
  sellCount: number;
  buyAmountYuan: string;
  sellAmountYuan: string;
  feesYuan: string;
  realizedPnlYuan: string;
};

export type PaperReviewSummary = {
  totalTradeCount: number;
  buyCount: number;
  sellCount: number;
  winningSellCount: number;
  allTimeRealizedPnlYuan: string;
  allTimeFeesYuan: string;
  monthTradeCount: number;
  monthRealizedPnlYuan: string;
  monthFeesYuan: string;
};

export type PaperReviewSnapshot = {
  account: PaperAccountSnapshot;
  month: string;
  days: PaperReviewDay[];
  summary: PaperReviewSummary;
  feePolicy: PaperFeePolicy;
  tPlusOneRule: string;
  simulationOnly: true;
};

export type PaperOrderRequest = {
  clientOrderId: string;
  symbol: string;
  side: PaperSide;
  quantity: number;
  reason: string;
};
