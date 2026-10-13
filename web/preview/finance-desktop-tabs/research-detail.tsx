import { Check, FileText } from "lucide-react";
import { VButton, VChip, VSurface } from "../../src/components/vui";

export function FinanceResearchDetailPreview({ title, empty, onAsk, onSources }: { title: string; empty: boolean; onAsk: (text: string) => void; onSources: () => void }) {
  if (empty) return <div className="research-detail-empty"><FileText size={28} /><h1>研究详情</h1><p>在右侧发起研究，报告、图表和资料在这里查看。</p><VButton variant="secondary" onPress={() => onAsk("分析贵州茅台的盈利质量、估值和风险")}>分析贵州茅台</VButton></div>;
  const company = title.split(" · ")[0];
  return <article className="research-detail" aria-label="当前会话研究报告">
    <div className="report-kicker"><span>综合研究</span><span>示例报告</span></div>
    <h1>{title}</h1>
    <p className="report-intro">围绕盈利质量、现金回款和估值建立研究判断，保留每项结论的资料依据。</p>
    <div className="report-summary-grid">{[["盈利质量", "核对现金回款", "利润与经营现金流相互印证"], ["估值与分红", "比较历史区间", "结合增长、分红和同业表现"], ["主要风险", "关注预期变化", "需求、资本开支和盈利预期"]].map(([label, value, text]) => <VSurface key={label} tone="inset" padding="normal" className="report-summary"><span>{label}</span><strong>{value}</strong><p>{text}</p></VSurface>)}</div>
    <section className="report-section"><div className="report-section-title"><h2>财务核对</h2><VChip tone="neutral">待核对</VChip></div><div className="financial-table-wrap"><table className="financial-table"><caption className="sr-only">{company}财务核对项目</caption><thead><tr><th>指标</th><th>核对内容</th><th>依据</th></tr></thead><tbody>{[["营业收入", "增长与回款是否同步", "利润表"], ["经营现金流", "与净利润变化是否一致", "现金流量表"], ["应收项目", "增速与收入是否匹配", "资产负债表"], ["分红与资本开支", "现金回报的持续性", "公告与财报附注"]].map(([a, b, c]) => <tr key={a}><th>{a}</th><td>{b}</td><td>{c}</td></tr>)}</tbody></table></div></section>
    <div className="report-bottom-grid"><section className="report-section"><h2>研究判断</h2><p>先确认{company}的盈利与现金回款，再评估估值是否反映增长预期。资料不足的项目保持待核对。</p><VButton variant="secondary" onPress={() => onAsk(`继续核对${company}的经营现金流与净利润，列出证据`)}>继续核对</VButton></section><section className="report-section"><h2>资料依据</h2>{["年度财务报表", "利润分配方案", "经营数据公告"].map(text => <div className="report-source" key={text}><FileText size={14} /><span>{text}</span><Check size={13} /></div>)}<VButton className="quiet" variant="ghost" onPress={onSources}>查看引用资料</VButton></section></div>
  </article>;
}
