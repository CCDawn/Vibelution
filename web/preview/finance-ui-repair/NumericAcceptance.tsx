import { useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { FinanceManualPositions } from "../../src/routes/finance/FinanceManualPositions";
import { FinanceWatchlistTable } from "../../src/routes/finance/FinanceWatchlistTable";
import { financialResearchKeys } from "../../src/api/financialResearch";
import type { FinancialManualPosition } from "../../src/api/financialPreferences";
import type { StockQuote } from "../../src/api/financialMarket";
const stock = {symbol:"sh600519",ticker:"600519",name:"贵州茅台",market:"上交所"};
const quote: StockQuote = { ...stock, price:1337.37, previousClose:1329, open:1330,high:1340,low:1320,change:8.37,changePercent:0.63,volumeLots:25079,turnoverYuan:3_360_000_000,peRatio:20.53,pbRatio:8.5,totalMarketCapYuan:1_671_822_000_000,timestamp:"2026-10-19T12:05:57+08:00" };
const initial: FinancialManualPosition = {id:"preview-holding",stock,quantity:100,costPrice:1200,currency:"CNY",note:"布局示例"};
export function quoteFixture() { return {source:"示例行情",fetchedAt:new Date().toISOString(),items:[{symbol:stock.symbol,quote,error:null}]}; }
export function NumericAcceptance({ mode, onResearch }: { mode: "manual" | "watchlist"; onResearch: () => void }) {
  const [client] = useState(()=>{ const q = new QueryClient({defaultOptions:{queries:{retry:false,refetchOnWindowFocus:false,gcTime:Infinity}}});q.setQueryData(financialResearchKeys.quotes([stock.symbol]),quoteFixture());return q; });
  const [positions,setPositions]=useState([initial]),[watchlist,setWatchlist]=useState([stock]);
  return <QueryClientProvider client={client}>{mode==="manual"?<FinanceManualPositions positions={positions} stock={stock} onSave={async change=>{setPositions(p=>change(p));}} pending={false} onSelectStock={()=>{}} researchDisabled={false} onResearchPrompt={onResearch} zh/>:<FinanceWatchlistTable watchlist={watchlist} onSelectStock={onResearch} onRemoveStock={removed=>setWatchlist(rows=>rows.filter(row=>row.symbol!==removed.symbol))} zh/>}</QueryClientProvider>;
}
