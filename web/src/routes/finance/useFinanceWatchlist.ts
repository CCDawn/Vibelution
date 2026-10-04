import { useCallback, useEffect, useState } from "react";
import type { StockIdentity } from "../../api/financialMarket";
import { stockIdentityFromUnknown } from "./stockResearchModel";

const defaultStock: StockIdentity = { symbol: "sh600519", ticker: "600519", name: "贵州茅台", market: "上交所" };
function readPreferences(key: string) {
  try {
    const raw: unknown = JSON.parse(localStorage.getItem(key) ?? "null");
    const stored = raw && typeof raw === "object" ? raw as Record<string, unknown> : {};
    const watchlist = Array.isArray(stored.watchlist) ? stored.watchlist.map(stockIdentityFromUnknown).filter((item): item is StockIdentity => item !== null).slice(0, 50) : [];
    return { selected: stockIdentityFromUnknown(stored.selected) ?? defaultStock, watchlist: [...new Map(watchlist.map((item) => [item.symbol, item])).values()] };
  } catch { return { selected: defaultStock, watchlist: [] as StockIdentity[] }; }
}
/** User preferences only. Quote, report and transcript data are not persisted here. */
export function useFinanceWatchlist(agentId: string) {
  const key = `vibelution.finance-stocks.v1:${agentId}`;
  const [preferences, setPreferences] = useState(() => readPreferences(key));
  const [storageError, setStorageError] = useState(false);
  useEffect(() => {
    try { localStorage.setItem(key, JSON.stringify(preferences)); setStorageError(false); }
    catch { setStorageError(true); }
  }, [key, preferences]);
  const selectStock = useCallback((stock: StockIdentity) => {
    const selected = stockIdentityFromUnknown(stock);
    if (selected) setPreferences((current) => ({ ...current, selected }));
  }, []);
  const toggleStock = useCallback((value: StockIdentity) => {
    const stock = stockIdentityFromUnknown(value);
    if (stock) setPreferences((current) => ({
      ...current,
      watchlist: current.watchlist.some((item) => item.symbol === stock.symbol)
        ? current.watchlist.filter((item) => item.symbol !== stock.symbol)
        : [...current.watchlist, stock].slice(-50),
    }));
  }, []);
  return { ...preferences, selectStock, toggleStock, storageError };
}
