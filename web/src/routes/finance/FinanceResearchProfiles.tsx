import { useEffect, useRef, useState } from "react";
import type { FinancialResearchProfile } from "../../api/financialPreferences";
import { VButton, VInput, VSelect, VStateSurface, VSurface, VTextarea } from "../../components/vui";
import type { FinanceResearchConfigValue } from "./FinanceResearchConfig";
import { ResearchProfileConflictError, saveResearchProfileChange, setResearchProfileDefault } from "./financialResearchProfilesModel";
import styles from "./FinanceResearchProfiles.styles";

export function FinanceResearchProfiles({ profiles, ready, value, onChange, onSave, pending, zh, selectedProfileId, onSelectProfile }: {
  profiles: FinancialResearchProfile[]; ready: boolean; value: FinanceResearchConfigValue;
  onChange: (value: FinanceResearchConfigValue) => void;
  onSave: (change: (current: FinancialResearchProfile[]) => FinancialResearchProfile[]) => Promise<unknown>;
  pending: boolean; zh: boolean;
  selectedProfileId: string; onSelectProfile: (id: string) => void;
}) {
  const selected = selectedProfileId;
  const [name, setName] = useState(""), [error, setError] = useState("");
  const saveGate = useRef(false);
  const editBaseline = useRef<FinancialResearchProfile | null>(null);
  const baselineId = useRef<string | null>(selected || null);
  useEffect(() => {
    if (selected !== (baselineId.current ?? "")) {
      baselineId.current = selected || null;
      const row = profiles.find((profile) => profile.id === selected);
      editBaseline.current = row ? { ...row } : null;
      setName(row?.name ?? "");
    } else if (selected && !editBaseline.current) {
      const row = profiles.find((profile) => profile.id === selected);
      if (row) { editBaseline.current = { ...row }; setName(row.name); }
    }
  }, [selected, profiles]);
  function apply(id: string) {
    onSelectProfile(id); const row = profiles.find((profile) => profile.id === id);
    baselineId.current = id || null; editBaseline.current = row ? { ...row } : null; setError(""); setName(row?.name ?? "");
    if (row) onChange({ ...value, scope: row.scope, depth: row.depth, period: row.period, instructions: row.instructions });
  }
  async function save(change: (current: FinancialResearchProfile[]) => FinancialResearchProfile[]) {
    if (saveGate.current || pending) return false;
    saveGate.current = true; setError("");
    try { await onSave(change); return true; } catch (cause) {
      if (cause instanceof ResearchProfileConflictError) {
        const messages = {
          changed: zh ? "该研究档案已在其他窗口修改，当前输入未覆盖最新内容。请刷新页面后重新编辑。" : "This research profile changed in another window. Your input did not overwrite it; refresh the page before editing again.",
          deleted: zh ? "该研究档案已在其他窗口删除，当前输入未保存。请刷新页面后重试。" : "This research profile was deleted in another window. Your input was not saved; refresh the page before retrying.",
          id_collision: zh ? "新档案标识已被占用，未覆盖现有档案。请重试。" : "The new profile ID is already in use. No existing profile was overwritten; try again.",
        };
        setError(messages[cause.reason]);
      } else setError(cause instanceof Error ? cause.message : (zh ? "保存失败" : "Save failed"));
      return false;
    }
    finally { saveGate.current = false; }
  }
  function saveProfile() {
    if (!name.trim()) return;
    const editingId = selected || null;
    const id = editingId ?? crypto.randomUUID();
    const baseline = editBaseline.current ? { ...editBaseline.current } : null;
    const row: FinancialResearchProfile = { id, name: name.trim(), scope: value.scope, depth: value.depth, period: value.period, instructions: value.instructions ?? "", isDefault: baseline?.isDefault ?? false };
    void save((current) => saveResearchProfileChange(current, row, editingId, baseline)).then((saved) => {
      if (saved && baselineId.current === editingId) { editBaseline.current = { ...row }; baselineId.current = id; onSelectProfile(id); }
    });
  }
  return <VSurface tone="panel" padding="normal" className={styles.root} ariaLabel={zh ? "研究档案" : "Research profiles"}>
    <div className={styles.toolbar}>
      <label className={styles.field}>{zh ? "研究档案" : "Profile"}<VSelect aria-label={zh ? "选择研究档案" : "Choose profile"} selectedKey={selected} options={[{ id: "", label: zh ? "新档案" : "New profile" }, ...profiles.map((row) => ({ id: row.id, label: `${row.name}${row.isDefault ? zh ? " · 默认" : " · Default" : ""}` }))]} onSelectionChange={(key) => apply(String(key))} /></label>
      <label className={styles.field}>{zh ? "档案名称" : "Profile name"}<VInput aria-label={zh ? "档案名称" : "Profile name"} value={name} maxLength={60} onChange={(event) => setName(event.target.value)} placeholder={zh ? "如：银行业盈利质量" : "e.g. Bank earnings quality"} /></label>
      <VButton isDisabled={!ready || pending || !name.trim() || (!selected && profiles.length >= 20)} onPress={saveProfile}>{zh ? "保存设置" : "Save settings"}</VButton>
      {selected ? <><VButton variant="secondary" isDisabled={pending} onPress={() => void save((current) => setResearchProfileDefault(current, selected))}>{zh ? "设为默认" : "Set default"}</VButton><VButton variant="ghost" isDisabled={pending} onPress={() => { const deletingId = selected; void save((current) => current.filter((row) => row.id !== deletingId)).then((saved) => { if (saved && baselineId.current === deletingId) { onSelectProfile(""); baselineId.current = null; editBaseline.current = null; setName(""); } }); }}>{zh ? "删除档案" : "Delete profile"}</VButton></> : null}
    </div>
    <label className={styles.field}>{zh ? "个股 / 行业分析要点" : "Stock / industry focus"}<VTextarea className={styles.instructions} aria-label={zh ? "档案分析要点" : "Profile focus"} value={value.instructions ?? ""} maxLength={1000} onChange={(event) => onChange({ ...value, instructions: event.target.value })} placeholder={zh ? "例如关注净息差、拨备覆盖率及同业估值。随本次研究发送。" : "Focus on margins, provisions and peer valuation. Included in this research."} /></label>
    {error ? <VStateSurface density="compact" tone="error" title={error} /> : null}
  </VSurface>;
}
