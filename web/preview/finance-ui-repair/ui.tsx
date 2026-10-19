import type { ReactNode } from "react";
import { VSurface } from "../../src/components/vui";
export const muted = "text-xs leading-5 text-vui-fg-tertiary";
export const field = "grid min-w-0 content-start gap-2 text-xs text-vui-fg-secondary";
export const number = "block whitespace-normal break-words [overflow-wrap:anywhere] text-right font-mono text-xs tabular-nums";
export function Block({ title, note, children, actions }: { title: string; note?: string; children: ReactNode; actions?: ReactNode }) {
  return <section className="grid min-w-0 content-start gap-4"><div className="flex flex-wrap items-start justify-between gap-3"><div><h2 className="m-0 text-sm font-semibold">{title}</h2>{note ? <p className={`${muted} mt-1 mb-0`}>{note}</p> : null}</div>{actions}</div>{children}</section>;
}
export function Panel({ children }: { children: ReactNode }) {
  return <VSurface tone="panel" padding="normal" className="grid min-w-0 content-start gap-4 !rounded-lg !border !border-vui-border-subtle !p-5 max-sm:!p-3">{children}</VSurface>;
}
export const stocks = [
  { id: "600519", name: "贵州茅台", market: "上交所", price: "1,337.37", change: "+0.63%" },
  { id: "000001", name: "平安银行", market: "深交所", price: "11.26", change: "−0.35%" },
  { id: "00700", name: "腾讯控股", market: "港交所", price: "468.20", change: "+1.12%" },
];
export type Stock = typeof stocks[number];
export const names: Record<string, string> = { workspace: "股票研究", general: "主题研究", team: "分析员协作", tasks: "研究任务", dashboard: "总览", watchlist: "自选行情", screen: "股票筛选", account: "模拟账户", portfolio: "组合研究", backtest: "历史回测", review: "交易复盘", reports: "报告中心", memory: "研究记忆", skills: "技能中心", learning: "学习中心" };
export const guides = ["核对一份年报", "识别新闻与公告", "避免估值口径混用", "理解复权和分红", "建立风险清单", "比较同行公司", "把想法变成筛选条件", "分析一次失败决策"];
