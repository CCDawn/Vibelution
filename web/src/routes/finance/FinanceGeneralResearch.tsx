import { useState } from "react";
import { Play, Search } from "lucide-react";
import { VButton, VInput, VSelect, VSurface, VTextarea } from "../../components/vui";
import { isValidResearchDate, localResearchDate, RESEARCH_DEPTH_INSTRUCTIONS, type ResearchDepth } from "./stockResearchModel";
import styles from "./FinanceKnowledgeCenter.styles";

export function generalResearchPrompt(topic: string, date: string, depth: ResearchDepth): string {
  return `请对以下主题开展投资研究：${topic.trim()}。分析截至 ${date}。${RESEARCH_DEPTH_INSTRUCTIONS[depth]}。使用当前可用的联网搜索和资料工具核对信息。按“结论、关键事实、受影响的行业与公司、多空论证、风险、证据来源”组织完整研究报告。每项外部事实标注可访问的来源和日期；区分事实、推论和缺失数据，不把候选股票或情景当成投资建议。`;
}

export function FinanceGeneralResearch({ disabled, pending, zh, onStart }: {
  disabled: boolean; pending: boolean; zh: boolean; onStart: (prompt: string, title: string, depth: ResearchDepth) => void;
}) {
  const [topic, setTopic] = useState("");
  const [date, setDate] = useState(localResearchDate());
  const [depth, setDepth] = useState<ResearchDepth>("standard");
  const examples = ["人工智能算力产业链的竞争格局与风险", "降息对银行、地产和消费行业的影响", "新能源行业的盈利拐点与供需变化"];
  return <div className={styles.page} data-finance-general-research>
    <h1 className={styles.heading}>{zh ? "通用研究" : "Topic research"}</h1>
    <VSurface tone="panel" className={styles.card}>
      <label className={styles.field}>{zh ? "研究主题" : "Research topic"}<VTextarea value={topic} maxLength={2000} minRows={5} aria-label={zh ? "研究主题" : "Research topic"} placeholder={zh ? "输入行业、政策、投资主题，或需要核实的问题" : "An industry, policy, investment theme or question"} onChange={(event) => setTopic(event.target.value)} /></label>
      <div className={styles.actions}><label className={styles.field}>{zh ? "分析日期" : "As of"}<VInput type="date" value={date} max={localResearchDate()} aria-invalid={!isValidResearchDate(date)} onChange={(event) => setDate(event.target.value)} /></label><label className={styles.field}>{zh ? "研究深度" : "Depth"}<VSelect selectedKey={depth} aria-label={zh ? "通用研究深度" : "Topic research depth"} onSelectionChange={(key) => setDepth(key as ResearchDepth)} options={[{ id: "brief", label: "1 · 快速" }, { id: "basic", label: "2 · 基础" }, { id: "standard", label: "3 · 标准" }, { id: "detailed", label: "4 · 深入" }, { id: "exhaustive", label: "5 · 全面" }]} /></label><VButton variant="primary" icon={<Play size={14} />} isPending={pending} isDisabled={disabled || !topic.trim() || !isValidResearchDate(date)} onPress={() => onStart(generalResearchPrompt(topic, date, depth), topic.trim().slice(0, 70), depth)}>{zh ? "开始研究" : "Start research"}</VButton></div>
    </VSurface>
    <div className={styles.examples}>{examples.map((example) => <VButton key={example} variant="secondary" icon={<Search size={14} />} className={styles.example} onPress={() => setTopic(example)}>{example}</VButton>)}</div>
  </div>;
}
