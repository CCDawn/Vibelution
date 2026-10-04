import styles from "./FinanceResearchConfig.styles";
import { Play, SlidersHorizontal } from "lucide-react";
import { VButton, VInput, VSelect, VSurface } from "../../components/vui";
import { isValidResearchDate, localResearchDate, type ResearchScope } from "./stockResearchModel";

export type FinanceResearchConfigValue = { period: string; date: string; scope: ResearchScope; depth: "brief" | "detailed" };
export function FinanceResearchConfig({ value, onChange, onStart, disabled, pending, zh }: { value: FinanceResearchConfigValue; onChange: (value: FinanceResearchConfigValue) => void; onStart: () => void; disabled: boolean; pending: boolean; zh: boolean }) {
  return <VSurface tone="panel" padding="normal" className={styles.surface} ariaLabel={zh ? "研究设置" : "Research settings"}>
    <div className={styles.heading}><strong className={styles.title}><SlidersHorizontal size={15} />{zh ? "发起研究" : "Start research"}</strong><span className={styles.caption}>{zh ? "财报 · 事件 · 风险" : "Financials · Events · Risks"}</span></div>
    <div className={styles.fields}>
      <label className={styles.field}>{zh ? "分析日期" : "As of"}<VInput type="date" value={value.date} max={localResearchDate()} aria-invalid={!isValidResearchDate(value.date)} aria-label={zh ? "分析日期" : "Analysis date"} onChange={(event) => onChange({ ...value, date: event.target.value })} /></label>
      <label className={styles.field}>{zh ? "报告期" : "Report period"}<VInput value={value.period} maxLength={40} placeholder="2024FY" aria-label={zh ? "报告期" : "Report period"} onChange={(event) => onChange({ ...value, period: event.target.value })} /></label>
      <label className={styles.field}>{zh ? "研究范围" : "Scope"}<VSelect selectedKey={value.scope} aria-label={zh ? "研究范围" : "Research scope"} onSelectionChange={(key) => onChange({ ...value, scope: key as ResearchScope })} options={[{ id: "comprehensive", label: zh ? "综合研究" : "Comprehensive" }, { id: "financial", label: zh ? "财报分析" : "Financials" }, { id: "events", label: zh ? "事件分析" : "Events" }, { id: "risk", label: zh ? "风险评估" : "Risks" }]} /></label>
      <label className={styles.field}>{zh ? "研究深度" : "Depth"}<VSelect selectedKey={value.depth} aria-label={zh ? "研究深度" : "Research depth"} onSelectionChange={(key) => onChange({ ...value, depth: key as "brief" | "detailed" })} options={[{ id: "brief", label: zh ? "简明" : "Brief" }, { id: "detailed", label: zh ? "详细核对" : "Detailed" }]} /></label>
      <VButton variant="primary" isDisabled={disabled || !isValidResearchDate(value.date)} onPress={onStart} icon={<Play size={14} />}>{pending ? (zh ? "正在启动" : "Starting") : (zh ? "开始研究" : "Start research")}</VButton>
    </div>
  </VSurface>;
}
