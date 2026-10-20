import { useState, type ReactNode } from "react";
import { ArrowRight, ChevronRight, FileText, FlaskConical, Settings2, Wallet } from "lucide-react";
import { VButton, VDenseOpsPage, VNativeInput, VNativeSelect, VuiProvider } from "../../src/components/vui";
import { calculate, demonstration, errorsFor, researchErrorsFor, initial, money, type Conditions } from "./model";
import "./preview.css";

export function InvestmentPreview() {
  const [draft, setDraft] = useState<Conditions>({ ...initial });
  const [saved, setSaved] = useState<Conditions | null>(null);
  const [report, setReport] = useState<Conditions | null>(null);
  const [attempted, setAttempted] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [scenario, setScenario] = useState("normal");
  const [expanded, setExpanded] = useState(false);
  const errors = researchErrorsFor(draft);
  const dirty = saved !== null && JSON.stringify(saved) !== JSON.stringify(draft);
  const stale = report !== null && (JSON.stringify(report) !== JSON.stringify(draft) || scenario !== "normal");
  const plan = report && !Object.keys(errorsFor(report)).length ? calculate(report) : null;
  const set = (key: keyof Conditions, value: string) => setDraft(current => ({ ...current, [key]: value }));
  const field = (key: keyof Conditions, label: string, children: ReactNode, help?: string) =>
    <div className="field" key={key}><label htmlFor={key}>{label}</label>{children}
      {attempted && errors[key] ? <span className="field-error" id={`${key}-error`}>{errors[key]}</span> : help ? <span className="field-help">{help}</span> : null}</div>;
  const number = (key: keyof Conditions, label: string, placeholder: string, help?: string) => field(key, label,
    <VNativeInput id={key} type="number" min="0" step="0.01" value={draft[key]} placeholder={placeholder} disabled={busy} aria-invalid={attempted && Boolean(errors[key])} aria-describedby={attempted && errors[key] ? `${key}-error` : undefined} onChange={e => set(key, e.target.value)} />, help);
  const select = (key: keyof Conditions, label: string, options: [string, string][], help?: string) => field(key, label,
    <VNativeSelect id={key} value={draft[key]} disabled={busy} aria-invalid={attempted && Boolean(errors[key])} onChange={e => set(key, e.target.value)}>
      {options.map(([value, text]) => <option value={value} key={value}>{text}</option>)}
    </VNativeSelect>, help);
  function run() {
    setAttempted(true);
    if (Object.keys(errors).length) { setNotice("请检查标出的数值；未填写的可选条件可以留空。"); return; }
    if (scenario === "failure") { setNotice("演示：行情服务暂时不可用。本次未生成新方案，可重试。"); return; }
    if (scenario === "missing") { setNotice("演示：候选缺少财报原文。本次只保留研究线索，不生成买入金额。"); return; }
    setSaved({ ...draft }); setBusy(true); setNotice("");
    const snapshot = { ...draft };
    window.setTimeout(() => { setReport(snapshot); setBusy(false); setNotice(""); }, 650);
  }
  function demo() {
    setDraft({ ...demonstration }); setSaved(null); setReport(null); setAttempted(false);
    setScenario("normal"); setNotice("已加载演示条件：保留 2000 元、接受亏损 1200 元、单股上限 40%。这些不是你的已确认偏好。");
  }
  return <VuiProvider><div className="investment-preview">
    <header className="app-bar"><div className="brand"><span className="brand-icon"><Wallet size={18} /></span><strong>炒股智能体</strong><ChevronRight size={14} /><span>我的投资方案</span></div><span className="preview-tag"><FlaskConical size={14} />交互预览</span></header>
    <div className="preview-disclosure"><span>虚构标的 · 固定演示行情 · 配置仅留在当前页面</span><VButton variant="ghost" onPress={demo} isDisabled={busy} trailingIcon={<ArrowRight size={14} />}>加载完整演示条件</VButton></div>
    <VDenseOpsPage fill={false} hideHeader className="plan-page" bodyClassName="plan-body" ariaLabel="投资配置与方案">
      <div className="page-heading"><div><h1>按我的条件分析投资</h1><p>A 股 · 不确定的条件可以先留空。</p></div></div>
      <div className="workspace">
        <aside className="configuration">
          <div className="section-heading"><h2><Settings2 size={18} />我的投资条件</h2><span className="muted">{dirty ? "有修改" : saved ? "本次已保留" : "待完善"}</span></div>
          <div className="primary-fields">
            {number("budget", "投资预算（元）", "例如 6000")}
            {select("horizon", "预计持有多久", [["3", "3 个月"], ["6", "6 个月"], ["12", "1 年"], ["36", "3 年及以上"]])}
            {number("loss", "能接受亏多少（元）", "可先留空")}
          </div>
          <details className="optional-fields">
            <summary>补充条件（可选）</summary>
            <div className="field-grid">
            {select("goal", "投资目标", [["", "尚未确定"], ["稳健增值", "稳健增值"], ["平衡增长", "平衡增长"], ["追求收益", "追求收益"]])}
            {select("flexible", "到期是否需要用钱", [["yes", "可以继续持有"], ["no", "到期需要用钱"]])}
            {number("reserve", "至少保留现金（元）", "待确认")}
            {number("concentration", "单只股票上限（%）", "待确认")}
            {select("permission", "可交易范围", [["", "尚未确认"], ["main", "A 股 · 沪深主板"]])}
            {select("holdings", "这笔预算对应的已有持仓", [["", "尚未确认"], ["none", "暂无，全部为现金"], ["yes", "已有持仓，需要录入"]])}
            </div>
          </details>
          <div className="config-actions"><p className="memory-note">正式版会记住你确认的条件，供此股票助手每次分析使用。此预览不会保存。</p><VButton variant="primary" onPress={run} isPending={busy} trailingIcon={<ArrowRight size={15} />}>{report ? "重新分析" : "开始分析"}</VButton></div>
        </aside>
        <main className="report-panel" aria-label="方案报告" aria-busy={busy}>
          <div className="section-heading"><h2><FileText size={18} />投资方案</h2><span className="status-pill">{busy ? "正在生成演示…" : stale ? "条件已变化" : report ? "演示结果" : "等待分析"}</span></div>
          <div role="status" aria-live="polite" className={notice ? "notice" : "notice hidden"}>{notice}</div>
          {stale && <div role="alert" className="stale">当前显示的是旧条件下的演示方案，请重新分析。旧方案不会自动套用到新预算。</div>}
          {!report ? <div className="empty-state"><p>分析后，先看资金怎么安排和主要风险。详细依据按需展开。</p></div> : !plan ? <div className="preliminary">
            <h3>可以先研究适合你的投资方向</h3>
            <p>本次预算 {money(Number(report.budget) * 100)}，计划 {report.horizon} 个月，{report.flexible === "yes" ? "可以继续持有" : "到期需要用钱"}。{report.loss ? `可接受亏损填写为 ${money(Number(report.loss) * 100)}。` : "可接受的最大亏损尚未确定。"}</p>
            <p>具体买入数量需要再核对持仓、交易权限和资金分配。未确认的条件保留为空，不自动当作你同意的偏好。</p>
            <span className="muted">这是研究流程预览；尚未调用股票助手或行情服务。</span>
          </div> : <div className={stale ? "report-content outdated" : "report-content"}>
            <div className="result-lead"><span className="eyebrow">资金安排 · 固定规则演示</span><h3>{plan.gross ? "先控制投入，再比较候选" : "当前预算与限制下，先保留现金"}</h3><p>{plan.gross ? `本示例按单股上限 ${report.concentration}% 和至少保留 ${money(Number(report.reserve) * 100)} 测算，扣除买入费用后保留 ${money(plan.cash)}。` : Number(report.loss) === 0 ? "你填写不能接受本金亏损，本示例不安排股票投入。" : "符合配置的资金不足以购买示例标的的一个交易单位，不降低你的仓位限制来凑单。"}</p></div>
            <div className="metrics"><div><span>本次预算</span><strong>{money(plan.budget)}</strong></div><div><span>预计投入 · 含买入费用</span><strong>{money(plan.cost)}</strong></div><div><span>剩余现金</span><strong>{money(plan.cash)}</strong></div></div>
            <div className="allocation" aria-label="资金占比"><div style={{ width: `${plan.budget ? plan.cost / plan.budget * 100 : 0}%` }} /></div><div className="allocation-label"><span>投入 {plan.budget ? (plan.cost / plan.budget * 100).toFixed(1) : 0}%</span><span>现金 {plan.budget ? (plan.cash / plan.budget * 100).toFixed(1) : 0}%</span></div>
            <p className="risk-brief">风险示例：股票部分下跌 20%，价格变动损失约 {money(Math.round(plan.gross * .2))}，不含费用。这不是实际亏损上限。</p>
            <details className="report-section expandable"><summary>候选、数量与研究依据</summary><div className="section-heading"><span className="muted">虚构名称与价格 · 非选股建议</span></div>
              <div className="table-wrap"><table><thead><tr><th>研究候选</th><th>示例价格</th><th>数量</th><th>金额 · 含费用</th><th>股票占比</th></tr></thead><tbody>{plan.rows.map(row => <tr key={row.name}><td><strong>{row.name}</strong><small>{row.shares ? "主板 · 100 股交易单位" : "不满足整手或仓位限制"}</small></td><td>{money(row.price * 100)}</td><td>{row.shares} 股</td><td>{money(row.cost)}</td><td>{row.weight.toFixed(1)}%</td></tr>)}</tbody></table></div>
              <p className="fine-print">示例买入佣金 0.03%，每笔最低 5 元，另计过户费 0.001%。实际应使用你的券商费率。本例费用 {money(plan.fees)}。</p>
              <VButton variant="ghost" onPress={() => setExpanded(!expanded)} aria-expanded={expanded} trailingIcon={<ChevronRight size={14} />}>{expanded ? "收起研究依据" : "查看研究依据与风险"}</VButton>
              {expanded && <div className="evidence">{plan.rows.map(row => <div key={row.name}><strong>{row.name}</strong><p>{row.reason}</p><p>{row.risk}</p><small>正式报告需附原文来源、报告期、行情时间与证据缺口；本预览没有真实研究证据。</small></div>)}</div>}
            </details>
            <details className="report-section expandable"><summary>如果买入后下跌</summary><p className="muted">假设股票部分同时下跌、现金不变。只算价格变动，不含交易费用。</p><div className="risk-grid">{[10, 20, 30].map(pct => <div key={pct}><span>股票下跌 {pct}%</span><strong>−{money(Math.round(plan.gross * pct / 100))}</strong><small>{plan.gross * pct / 100 > Number(report.loss) * 100 ? "超过你填写的承受金额" : "未超过填写金额"}</small></div>)}</div><p className="fine-print">情景测算不代表最大损失。跳空、跌停等情况可能导致实际亏损更大。</p></details>
            <details className="snapshot"><summary>本次采用的投资条件</summary><dl><dt>预算 / 最少现金</dt><dd>{money(Number(report.budget) * 100)} / {money(Number(report.reserve) * 100)}</dd><dt>目标 / 期限</dt><dd>{report.goal} / {report.horizon} 个月，{report.flexible === "yes" ? "可继续持有" : "到期需要用钱"}</dd><dt>风险 / 单股上限</dt><dd>{money(Number(report.loss) * 100)} / {report.concentration}%</dd><dt>范围 / 持仓</dt><dd>沪深主板 / 无已有持仓</dd></dl><p className="fine-print">本预览只有金额规则计算，目标与期限仅展示在条件快照中；正式版需将其传入研究。</p></details>
          </div>}
          <details className="preview-options"><summary>预览演示选项</summary><div className="preview-controls"><label htmlFor="scenario">预览状态</label><VNativeSelect id="scenario" value={scenario} disabled={busy} onChange={e => { setScenario(e.target.value); setNotice(""); }}><option value="normal">数据齐全（演示）</option><option value="missing">财报证据不足</option><option value="failure">行情获取失败</option></VNativeSelect></div></details>
        </main>
      </div>
    </VDenseOpsPage>
  </div></VuiProvider>;
}
