import { useState, type FormEvent } from "react";
import { Search } from "lucide-react";
import type { StockIdentity } from "../../api/financialMarket";
import { VButton, VSurface, VTabs, VTextarea } from "../../components/vui";
import { FinanceMarketExplorer } from "./FinanceMarketExplorer";
import { localResearchDate } from "./stockResearchModel";
import styles from "./FinanceScreenWorkspace.styles";

const EXAMPLE_CRITERIA = [
  "PE低于20，PB低于3，成交额高于10亿元",
  "涨幅超过3%，成交额高于5亿元",
  "股价10到50元，成交量超过5万手",
] as const;

export function financeScreenAgentPrompt(criteria: string, date = localResearchDate()): string {
  return [
    `请研究以下股票筛选条件，生成筛选报告。分析截至 ${date}。按条件筛选股票，列出候选、筛选依据和数据限制。`,
    `用户选股条件：${criteria.trim()}`,
    "请调用 financial_market_screen_tool 获取真实候选，不得虚构或补齐股票数据。",
    "回答需列出行情来源、抓取时间、已加载数量/行情池总数、覆盖是否完整和符合条件数量；覆盖不完整时明确结果仅基于已加载范围。",
    "若工具不支持某项条件或调用失败，说明具体缺项，不要用猜测替代。",
  ].join("\n\n");
}

export type FinanceScreenWorkspaceProps = {
  agentId: string;
  currentStock: StockIdentity;
  onResearchPrompt: (prompt: string) => void;
  onSelectStock: (stock: StockIdentity) => void;
  disabled?: boolean;
  zh: boolean;
};

export function FinanceScreenWorkspace({
  agentId,
  currentStock,
  onResearchPrompt,
  onSelectStock,
  disabled = false,
  zh,
}: FinanceScreenWorkspaceProps) {
  const [tab, setTab] = useState("smart");
  const [criteria, setCriteria] = useState("");
  const [error, setError] = useState("");

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const value = criteria.trim();
    if (!value) {
      setError(zh ? "请描述选股条件" : "Describe your screening criteria");
      return;
    }
    setError("");
    onResearchPrompt(financeScreenAgentPrompt(value));
  }

  return <div className={styles.root}>
    <VTabs
      value={tab}
      onValueChange={setTab}
      aria-label={zh ? "选股方式" : "Screening mode"}
      items={[
        { id: "smart", label: zh ? "智能选股" : "AI screening" },
        { id: "advanced", label: zh ? "高级筛选" : "Advanced filters" },
      ]}
    />
    {tab === "smart" ? <VSurface className={styles.smartPanel} padding="normal" ariaLabel={zh ? "智能选股条件" : "AI screening criteria"}>
      <form className={styles.form} onSubmit={submit}>
        <label className={styles.criteriaLabel} htmlFor="finance-screen-criteria">{zh ? "选股条件" : "Screening criteria"}</label>
        <VTextarea
          id="finance-screen-criteria"
          aria-label={zh ? "选股条件" : "Screening criteria"}
          value={criteria}
          onChange={(event) => setCriteria(event.target.value)}
          maxLength={1000}
          minRows={3}
          placeholder={zh ? "例如：PE低于20，PB低于3，成交额高于10亿元" : "e.g. PE below 20, PB below 3, turnover above CNY 1bn"}
          disabled={disabled}
          className={styles.criteriaInput}
        />
        <div className={styles.examples} aria-label={zh ? "选股示例" : "Screening examples"}>
          {EXAMPLE_CRITERIA.map((example) => <VButton
            key={example}
            type="button"
            variant="ghost"
            isDisabled={disabled}
            className={styles.example}
            onPress={() => { setCriteria(example); setError(""); }}
          >{example}</VButton>)}
        </div>
        {error ? <p className={styles.error} role="alert">{error}</p> : null}
        <div className={styles.actions}>
          <VButton type="submit" variant="primary" icon={<Search size={14} />} isDisabled={disabled || !criteria.trim()}>
            {zh ? "开始选股" : "Start screening"}
          </VButton>
        </div>
      </form>
    </VSurface> : <>
      <FinanceMarketExplorer
        agentId={agentId}
        mode="screen"
        stock={currentStock}
        onSelectStock={onSelectStock}
        onResearchPrompt={onResearchPrompt}
        researchDisabled={disabled}
        zh={zh}
      />
    </>}
  </div>;
}
