export type PaperSide = "buy" | "sell";
export type PaperValuationStatus = "fresh" | "stale" | "unavailable";

export type PaperFeePolicy = {
  feeModel?: string | null;
  effectiveDate?: string | null;
  commissionRate: string;
  minimumCommissionYuan: string;
  commissionIncludes?: string[];
  transferFeeRate?: string | null;
  sellStampDutyRate: string;
  transferFeeIncluded: boolean;
  roundingStatus?: string | null;
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

export type PaperOrderQuantityRule = {
  symbol: string;
  version: string;
  board: string;
  minimumBuyShares: number;
  buyIncrement: number;
  minimumSellShares: number;
  sellIncrement: number;
  residualSellThreshold: number;
  maximumOrderShares: number;
  supportedForSimulation: boolean;
  unsupportedReason: string | null;
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
  transferFeeYuan?: string;
  handlingFeeYuan?: string;
  regulatoryFeeYuan?: string;
  brokerCommissionYuan?: string;
  feeModel?: string;
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
  tradeDate?: string | null;
  isTradingDay?: boolean | null;
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
  orderQuantityRule?: PaperOrderQuantityRule | null;
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
