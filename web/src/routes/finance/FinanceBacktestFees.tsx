import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import type { AIBacktestFeePolicyAudit, AIBacktestRun } from "../../api/types/financialBacktests";
import { VButton, VDenseTable, VSurface } from "../../components/vui";
import styles from "./FinanceBacktestFees.styles";

const amount = (value: number | undefined) => typeof value === "number" && Number.isFinite(value) ? value.toFixed(2) : "—";
const officialSource = (value: string) => {
  try {
    const url = new URL(value);
    return url.protocol === "https:" && !url.username && !url.password && ["sse.com.cn", "szse.cn", "csrc.gov.cn", "chinaclear.cn", "chinatax.gov.cn", "mof.gov.cn"].some(host => url.hostname === host || url.hostname.endsWith(`.${host}`));
  } catch { return false; }
};

export function FinanceBacktestFees({ audit, run, zh }: { audit?: AIBacktestFeePolicyAudit | null; run?: AIBacktestRun; zh: boolean }) {
  const [open, setOpen] = useState(false);
  if (!audit) return null;
  const rows = ([ ["strategy", run?.orders], ["benchmark", run?.benchmarkOrders] ] as const).flatMap(([account, orders]) => (orders ?? []).filter(row => (row.filledShares ?? 0) > 0).map((row, index) => ({ ...row, account, key: `${account}:${row.date}:${row.symbol || ""}:${index}` })));
  return <VSurface tone="panel" padding="compact" className={styles.panel}>
    <div className={styles.row}><strong>{zh ? "沪深历史费用" : "Historical Shanghai / Shenzhen fees"}</strong><span className={styles.note}>{zh ? "佣金含规费 · 过户费另计" : "Regulatory fees included in commission · transfer fee separate"}</span></div>
    <VButton variant="ghost" aria-expanded={open} icon={open ? <ChevronDown size={14} /> : <ChevronRight size={14} />} onPress={() => setOpen(value => !value)}>{zh ? "费用明细与依据" : "Fee ledger and sources"}</VButton>
    {open ? <>
      {run ? <div className={styles.table}><VDenseTable ariaLabel={zh ? "AI回测费用审计" : "AI backtest fee audit"} resizable rows={rows} getRowKey={row => row.key} emptyText={zh ? "没有成交费用" : "No fill fees"} columns={[
        { id: "date", header: zh ? "成交日" : "Fill date", render: row => row.date },
        { id: "symbol", header: zh ? "股票" : "Symbol", render: row => row.symbol || run.symbol || "—" },
        { id: "account", header: zh ? "账户" : "Account", render: row => row.account === "strategy" ? (zh ? "AI策略" : "Strategy") : (zh ? "持有基准" : "Benchmark") },
        { id: "commission", header: zh ? "佣金合计" : "Total commission", render: row => amount(row.commission) },
        { id: "handling", header: zh ? "内含经手费" : "Included handling", render: row => amount(row.handlingFee) },
        { id: "regulatory", header: zh ? "内含证管费" : "Included regulatory", render: row => amount(row.regulatoryFee) },
        { id: "broker", header: zh ? "券商佣金差额" : "Broker remainder", render: row => amount(row.brokerCommission) },
        { id: "transfer", header: zh ? "过户费" : "Transfer", render: row => amount(row.transferFee) },
        { id: "stamp", header: zh ? "印花税" : "Stamp duty", render: row => amount(row.stampDuty) },
        { id: "total", header: zh ? "总扣费" : "Total fee", render: row => amount(row.fee) },
      ]} /></div> : null}
      <p className={styles.note}>{audit.startDate} — {audit.endDate} · {zh ? (audit.notice || "每个模拟订单计一次最低佣金；四舍五入到分，券商实际结算未核实。") : "One minimum commission per simulated order; round half up to cents, broker settlement unverified."}</p>
      <div className={styles.row}>{audit.sourceURLs.filter(officialSource).map((url, index) => <a key={url} href={url} className={styles.sourceLink} target="_blank" rel="noreferrer">{zh ? "官方依据" : "Official source"} {index + 1}</a>)}</div>
    </> : null}
  </VSurface>;
}
