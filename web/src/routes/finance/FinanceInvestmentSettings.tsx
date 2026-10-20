import { useRef, useState } from "react";
import type { FinancialInvestmentProfile } from "../../api/types/financialPreferences";
import { VButton, VCheckbox, VInput, VSelect, VStateSurface } from "../../components/vui";
import { useFinanceWorkspace } from "./useFinanceWorkspace";
import styles from "./FinanceInvestmentSettings.styles";

function profileFingerprint(value: FinancialInvestmentProfile | null) {
  return value === null ? "null" : JSON.stringify(Object.entries(value).sort(([a], [b]) => a.localeCompare(b)));
}

/** Mounted afresh when the settings dialog opens; edits never overwrite a newer profile. */
export function FinanceInvestmentSettings({ agentId, zh }: { agentId: string; zh: boolean }) {
  const workspace = useFinanceWorkspace(agentId);
  if (workspace.query.isPending) return <p>{zh ? "正在读取投资条件…" : "Loading investment conditions…"}</p>;
  if (workspace.query.isError || !workspace.query.data) return <VStateSurface tone="error" title={zh ? "投资条件读取失败" : "Could not load conditions"} actions={<VButton onPress={() => void workspace.query.refetch()}>{zh ? "重试" : "Retry"}</VButton>} />;
  return <InvestmentForm key={agentId} initial={workspace.query.data.investmentProfile ?? null} pending={workspace.pending} zh={zh} onSave={async (profile, baseline) => {
    await workspace.update(current => {
      if (profileFingerprint(current.investmentProfile ?? null) !== profileFingerprint(baseline)) throw new Error(zh ? "投资条件已在其他页面修改，请关闭后重新打开再保存。" : "Conditions changed elsewhere. Close and reopen before saving.");
      return { investmentProfile: profile };
    });
  }} />;
}

function InvestmentForm({ initial, pending, zh, onSave }: {
  initial: FinancialInvestmentProfile | null; pending: boolean; zh: boolean;
  onSave: (profile: FinancialInvestmentProfile, baseline: FinancialInvestmentProfile | null) => Promise<void>;
}) {
  const baseline = useRef(initial);
  const gate = useRef(false);
  const [values, setValues] = useState(() => ({
    budgetCny: String(initial?.budgetCny ?? ""), horizonMonths: String(initial?.horizonMonths ?? ""),
    availableCashCny: String(initial?.availableCashCny ?? ""),
    maxLossCny: String(initial?.maxLossCny ?? ""), cashReserveCny: String(initial?.cashReserveCny ?? ""),
    maxPositionPct: String(initial?.maxPositionPct ?? ""),
  }));
  const [flexible, setFlexible] = useState<boolean | null>(initial?.flexibleHorizon ?? null);
  const [holdings, setHoldings] = useState(initial?.holdingsStatus ?? "unknown");
  const [more, setMore] = useState(false), [error, setError] = useState(""), [saved, setSaved] = useState(false);
  function field(key: keyof typeof values, label: string) {
    return <label className={styles.field}>{label}<VInput aria-label={label} type="number" min={key === "horizonMonths" ? 1 : 0} step={key === "horizonMonths" ? 1 : "any"} value={values[key]} placeholder={zh ? "未确认" : "Unknown"} disabled={pending} onChange={event => { setValues(current => ({ ...current, [key]: event.target.value })); setSaved(false); }} /></label>;
  }
  async function save() {
    if (gate.current) return;
    gate.current = true; setError(""); setSaved(false);
    try {
      const numbers = Object.fromEntries(Object.entries(values).map(([key, value]) => [key, value.trim() ? Number(value) : null]));
      if (Object.values(numbers).some(value => value !== null && !Number.isFinite(value))) throw new Error(zh ? "请输入有效数字" : "Enter valid numbers");
      const profile: FinancialInvestmentProfile = { ...numbers, market: "CN", flexibleHorizon: flexible, holdingsStatus: holdings };
      await onSave(profile, baseline.current);
      // The server normalizes absent values; retain the complete sent shape as the next baseline.
      baseline.current = profile; setSaved(true);
    } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
    finally { gate.current = false; }
  }
  return <div className={styles.root}>
    <p className={styles.caption}>{zh ? "仅供这个助手使用。保存后每轮分析都会读取；留空表示未确认。" : "Private to this advisor and read on each turn. Blank means unknown."}</p>
    <div className={styles.fields}>
      {field("budgetCny", zh ? "投资预算（元）" : "Budget (CNY)")}
      {field("availableCashCny", zh ? "当前可用现金（元）" : "Available cash (CNY)")}
      {field("horizonMonths", zh ? "预计持有（月）" : "Horizon (months)")}
      {field("maxLossCny", zh ? "最大可接受亏损（元）" : "Loss tolerance (CNY)")}
    </div>
    <VCheckbox isSelected={flexible === true} isDisabled={pending} onChange={value => { setFlexible(value === true); setSaved(false); }}>{zh ? "到期后可以继续持有" : "I can hold beyond this horizon"}</VCheckbox>
    <p className={styles.caption}>{zh ? "亏损承受额用于评估风险，不保证实际亏损不会超过它。" : "Loss tolerance guides risk assessment; actual losses may exceed it."}</p>
    <VButton variant="ghost" aria-expanded={more} onPress={() => setMore(!more)}>{zh ? more ? "收起其他条件" : "其他条件" : more ? "Fewer conditions" : "Other conditions"}</VButton>
    {more ? <div className={styles.fields}>
      {field("cashReserveCny", zh ? "保留现金（元）" : "Cash reserve (CNY)")}
      {field("maxPositionPct", zh ? "单股仓位上限（%）" : "Single-stock cap (%)")}
      <label className={styles.field}>{zh ? "现有持仓" : "Holdings"}<VSelect aria-label={zh ? "现有持仓" : "Holdings"} selectedKey={holdings} isDisabled={pending} onSelectionChange={key => { setHoldings(String(key) as typeof holdings); setSaved(false); }} options={[{ id: "unknown", label: zh ? "未确认" : "Unknown" }, { id: "none", label: zh ? "没有持仓" : "No holdings" }, { id: "recorded", label: zh ? "已在手动持仓记录" : "Recorded in manual holdings" }]} /></label>
    </div> : null}
    {error ? <VStateSurface tone="error" density="compact" title={error} /> : null}
    {saved ? <p role="status">{zh ? "已保存，下次分析将读取最新条件。" : "Saved. The next analysis will read these conditions."}</p> : null}
    <VButton isDisabled={pending} onPress={() => void save()}>{zh ? pending ? "正在保存…" : "保存投资条件" : pending ? "Saving…" : "Save conditions"}</VButton>
  </div>;
}
