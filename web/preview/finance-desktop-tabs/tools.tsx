import { createContext, useContext, useState, type ReactNode } from "react";
import { ArrowUpRight, Check, FileText, Search } from "lucide-react";
import { VButton, VChip, VInput, VSelect, VSurface, VTabs } from "../../src/components/vui";

const stocks = [
  { code: "600519", name: "贵州茅台", price: "1,450.00", change: "+0.68%" },
  { code: "300750", name: "宁德时代", price: "265.20", change: "+1.12%" },
  { code: "600036", name: "招商银行", price: "41.80", change: "−0.45%" },
  { code: "600900", name: "长江电力", price: "28.60", change: "+0.32%" },
];

function useToolState() {
  const [query, setQuery] = useState("");
  const [period, setPeriod] = useState("day");
  const [strategy, setStrategy] = useState("ma");
  const [backtested, setBacktested] = useState(false);
  const [source, setSource] = useState("annual");
  const [symbol, setSymbol] = useState("600519");
  const [from, setFrom] = useState("2023-01-01");
  const [to, setTo] = useState("2025-12-31");
  const [cash, setCash] = useState("100000");
  return { query, setQuery, period, setPeriod, strategy, setStrategy, backtested, setBacktested, source, setSource, symbol, setSymbol, from, setFrom, to, setTo, cash, setCash };
}
const ToolState = createContext<ReturnType<typeof useToolState> | null>(null);
export function FinanceToolPreviewState({ children }: { children: ReactNode }) {
  const state = useToolState();
  return <ToolState.Provider value={state}>{children}</ToolState.Provider>;
}
export function FinanceToolPreview({ area, company = "贵州茅台", onAsk }: { area: string; company?: string; onAsk: (text: string) => void }) {
  const state = useContext(ToolState);
  if (!state) throw new Error("Preview tool state provider is required");
  const { query, setQuery, period, setPeriod, strategy, setStrategy, backtested, setBacktested, source, setSource, symbol, setSymbol, from, setFrom, to, setTo, cash, setCash } = state;
  if (["watchlist", "screen"].includes(area)) return <div className="tool-content">
    <div className="tool-search"><Search size={15} /><VInput aria-label="查找A股" placeholder="名称 / 股票代码" value={query} onChange={e => setQuery(e.target.value)} /></div>
    {area === "screen" ? <VSelect aria-label="筛选条件" defaultSelectedKey="cash" options={[{ id: "cash", label: "经营现金流为正" }, { id: "dividend", label: "连续三年分红" }]} /> : null}
    <div className="quote-list">{stocks.filter(s => `${s.name}${s.code}`.includes(query)).map(s => <div className="quote-row" key={s.code}><div><strong>{s.name}</strong><small>{s.code}</small></div><div className="quote-values"><strong>{s.price}</strong><small className={s.change.startsWith("−") ? "market-down" : "market-up"}>{s.change}</small></div><VButton variant="ghost" className="quiet tool-mini" onPress={() => onAsk(`研究${s.name}（${s.code}）的盈利质量与风险`)}>研究</VButton></div>)}</div>
    <VSurface tone="inset" padding="normal" className="chart-card"><div className="chart-heading"><strong>贵州茅台</strong><span>600519</span></div><VTabs value={period} onValueChange={setPeriod} aria-label="K线周期" items={[{ id: "day", label: "日K" }, { id: "week", label: "周K" }, { id: "month", label: "月K" }]} /><svg className="price-chart" viewBox="0 0 360 160" role="img" aria-label={`${period === "day" ? "日" : period === "week" ? "周" : "月"}K示例走势`}><path d="M0 40H360M0 80H360M0 120H360" stroke="currentColor" opacity=".08" /><path d={period === "day" ? "M0 110L20 118L40 94L60 99L80 76L100 82L120 62L140 73L160 56L180 71L200 60L220 36L240 47L260 26L280 42L300 29L320 16L340 25L360 12" : period === "week" ? "M0 130L40 118L80 128L120 78L160 92L200 70L240 76L280 42L320 50L360 26" : "M0 135L60 102L120 120L180 78L240 68L300 82L360 30"} stroke="var(--accent-cool)" strokeWidth="2" fill="none" /><text x="2" y="155" fill="currentColor" opacity=".5" fontSize="10">09-14</text><text x="318" y="155" fill="currentColor" opacity=".5" fontSize="10">10-13</text></svg></VSurface>
    <p className="tool-note">示例行情 · 用于检查布局</p>
  </div>;
  if (area === "backtest") return <div className="tool-content">
    <div className="field-line"><span>标的</span><VInput aria-label="回测标的" value={symbol} onChange={e => { setSymbol(e.target.value); setBacktested(false); }} /></div>
    <div className="field-line"><span>策略</span><VSelect aria-label="回测策略" selectedKey={strategy} onSelectionChange={v => { setStrategy(String(v)); setBacktested(false); }} options={[{ id: "ma", label: "双均线策略" }, { id: "hold", label: "买入持有" }]} /></div>
    <div className="field-line"><span>开始日期</span><VInput type="date" aria-label="回测开始日期" value={from} onChange={e => { setFrom(e.target.value); setBacktested(false); }} /></div>
    <div className="field-line"><span>结束日期</span><VInput type="date" aria-label="回测结束日期" value={to} onChange={e => { setTo(e.target.value); setBacktested(false); }} /></div>
    <div className="field-line"><span>初始资金</span><VInput aria-label="回测初始资金" type="number" value={cash} onChange={e => { setCash(e.target.value); setBacktested(false); }} min="1" /></div>
    <VButton variant="primary" className="tool-run" isDisabled={!/^\d{6}$/.test(symbol) || !from || !to || from > to || !(Number(cash) > 0)} onPress={() => setBacktested(true)}>运行示例回测</VButton>
    {backtested ? <><VSurface tone="inset" padding="normal"><div className="result-heading"><Check size={15} /><strong>示例结果</strong><VChip tone="neutral">模拟</VChip></div><div className="metric-list">{[["累计收益", strategy === "ma" ? "+12.6%" : "+8.4%"], ["最大回撤", "−9.8%"], ["成交次数", strategy === "ma" ? "18" : "2"], ["基准收益", "+8.4%"]].map(([name, value]) => <div key={name}><span>{name}</span><strong>{value}</strong></div>)}</div></VSurface><VButton variant="secondary" onPress={() => onAsk("解释这次示例回测的收益、最大回撤和策略失效风险")}>在会话中分析</VButton></> : <p className="tool-note">确定性示例，不调用行情或模型。</p>}
  </div>;
  if (["sources", "reports"].includes(area)) return <div className="tool-content"><VTabs value={source} onValueChange={setSource} aria-label="资料类型" items={[{ id: "annual", label: "财报" }, { id: "news", label: "公告" }]} />{(source === "annual" ? ["2025年年度报告", "2025年现金流量表", "2025年利润分配方案"] : ["年度股东大会公告", "经营数据公告"]).map((name, i) => <VSurface key={name} tone="row" padding="normal" className="source-row"><div className="source-title"><FileText size={16} /><strong>{name}</strong></div><p>{company} · {source === "annual" ? `第 ${32 + i * 8} 页` : "公告正文"}</p><VButton variant="ghost" className="quiet" trailingIcon={<ArrowUpRight size={13} />} onPress={() => onAsk(`核对${company}${name}中的数据，并列出来源`)}>引用到会话</VButton></VSurface>)}<p className="tool-note">示例资料，未连接真实文件。</p></div>;
  if (["account", "portfolio", "review"].includes(area)) return <div className="tool-content"><VSurface tone="inset" padding="normal"><div className="metric-list">{[["模拟总资产", "100,000.00"], ["可用资金", "46,200.00"], ["持仓市值", "53,800.00"]].map(([name, value]) => <div key={name}><span>{name}</span><strong>{value}</strong></div>)}</div></VSurface>{stocks.slice(0, 3).map(s => <div key={s.code} className="quote-row"><div><strong>{s.name}</strong><small>{s.code}</small></div><strong>{s.price}</strong></div>)}<VButton variant="secondary" onPress={() => onAsk("分析当前模拟组合的集中度、回撤风险和资金安排")}>分析模拟组合</VButton><p className="tool-note">示例虚拟账本。</p></div>;
  const content: Record<string, string[]> = {
    process: ["读取财报与公告", "核对利润和现金回款", "比较估值与分红", "整理风险与研究结论"],
    team: ["财报分析员", "市场分析员", "估值分析员", "风险分析员"],
    tasks: ["贵州茅台财报研究", "宁德时代现金流核对", "消费板块横向比较"],
    dashboard: ["今日研究 3 项", "已完成报告 8 份", "待核对资料 2 项"],
    memory: ["盈利质量研究结论", "分红与资本开支核对", "估值比较记录"],
    skills: ["财报分析", "A股估值比较", "组合风险评估"],
    learning: ["阅读现金流量表", "理解估值区间", "复盘投资假设"],
  };
  return <div className="tool-content">{(content[area] || content.process).map((text, i) => <div className="process-row" key={text}><span className="step-number">{i + 1}</span><span>{text}</span>{area === "process" ? <Check size={14} className="step-check" /> : <VButton variant="ghost" className="quiet tool-mini" onPress={() => onAsk(text)}>查看</VButton>}</div>)}{area !== "process" ? <p className="tool-note">示例内容 · 操作回到当前会话</p> : <p className="tool-note">与当前会话关联的示例过程。</p>}</div>;
}
