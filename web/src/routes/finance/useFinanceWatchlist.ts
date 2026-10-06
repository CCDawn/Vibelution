import { useCallback, useEffect, useRef, useState } from "react";
import type { StockIdentity } from "../../api/financialMarket";
import type { FinancialWatchStock } from "../../api/financialPreferences";
import { stockIdentityFromUnknown } from "./stockResearchModel";
import { useFinanceWorkspace } from "./useFinanceWorkspace";

const defaultStock: StockIdentity = { symbol: "sh600519", ticker: "600519", name: "贵州茅台", market: "上交所" };
function readPreferences(key: string) {
  try {
    const raw: unknown = JSON.parse(localStorage.getItem(key) ?? "null");
    const stored = raw && typeof raw === "object" ? raw as Record<string, unknown> : {};
    const watchlist = Array.isArray(stored.watchlist) ? stored.watchlist.map(stockIdentityFromUnknown).filter((item): item is StockIdentity => item !== null).slice(0, 50).map((stock) => ({ ...stock, tags: [] as string[], note: "" })) : [];
    const selected = stockIdentityFromUnknown(stored.selected);
    return { selected: selected ?? defaultStock, watchlist: [...new Map(watchlist.map((item) => [item.symbol, item])).values()], hasStored: Boolean(selected || watchlist.length) };
  } catch { return { selected: defaultStock, watchlist: [] as FinancialWatchStock[], hasStored: false }; }
}
/** Server settings are authoritative. Read the old browser settings only for migration. */
export function useFinanceWatchlist(agentId: string) {
  const key = `vibelution.finance-stocks.v1:${agentId}`;
  const [legacy] = useState(() => readPreferences(key));
  const workspace = useFinanceWorkspace(agentId);
  const [preferences, setPreferences] = useState({ selected: legacy.selected, watchlist: legacy.watchlist });
  const hydrated = useRef(false);
  useEffect(() => {
    const data = workspace.query.data;
    if (!data || workspace.pending) return;
    if (!hydrated.current) {
      hydrated.current = true;
      if (data.revision === 0 && legacy.hasStored) {
        void workspace.update((current) => current.revision === 0 ? { watchlist: legacy.watchlist, selectedStock: legacy.selected } : null).catch(() => undefined);
        return;
      }
    }
    setPreferences({ selected: data.selectedStock ?? defaultStock, watchlist: data.watchlist });
  }, [workspace.query.data, workspace.pending]);
  const selectStock = useCallback((value: StockIdentity) => {
    const selected = stockIdentityFromUnknown(value);
    if (!selected) return;
    setPreferences((current) => ({ ...current, selected }));
    void workspace.update({ selectedStock: selected }).catch(() => undefined);
  }, [workspace.update]);
  const toggleStock = useCallback((value: StockIdentity) => {
    const stock = stockIdentityFromUnknown(value);
    if (!stock) return;
    const toggle = (rows: FinancialWatchStock[]) => rows.some((item) => item.symbol === stock.symbol) ? rows.filter((item) => item.symbol !== stock.symbol) : rows.length >= 50 ? rows : [...rows, { ...stock, tags: [], note: "" }];
    setPreferences((current) => ({
      ...current,
      watchlist: toggle(current.watchlist),
    }));
    void workspace.update((current) => {
      if (current.watchlist.length >= 50 && !current.watchlist.some((item) => item.symbol === stock.symbol)) throw new Error("自选最多50只，请先移除一只股票");
      return { watchlist: toggle(current.watchlist) };
    }).catch(() => undefined);
  }, [workspace.update]);
  const editStock = useCallback((symbol: string, tags: string[], note: string) => workspace.update((current) => ({ watchlist: current.watchlist.map((stock) => stock.symbol === symbol ? { ...stock, tags, note } : stock) })), [workspace.update]);
  return { ...preferences, selectStock, toggleStock, editStock, storageError: Boolean(workspace.error || workspace.query.isError), error: workspace.error || (workspace.query.error?.message ?? ""), pending: workspace.pending, workspace };
}
