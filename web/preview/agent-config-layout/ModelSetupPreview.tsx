import { useState } from "react";
import { Check, ChevronDown, Search, Image, Wrench } from "lucide-react";
import { VButton, VNativeButton, VCheckbox, VPopover, VInput, VSelect } from "../../src/components/vui";
import { flatControl, selectControl } from "./previewStyles";
import type { Draft } from "./fixtures";

// Deterministic catalog examples. Readiness is fixture metadata, not a live test.
const models = [
  { id: "OpenAI / GPT-5.4", label: "GPT-5.4", provider: "OpenAI", image: true, tools: true, ready: true, reason: "", efforts: ["默认", "低", "中", "高"] },
  { id: "OpenAI / GPT-5.4 mini", label: "GPT-5.4 mini", provider: "OpenAI", image: true, tools: true, ready: true, reason: "", efforts: ["默认", "低", "中", "高"] },
  { id: "Anthropic / Claude Sonnet 4.6", label: "Claude Sonnet 4.6", provider: "Anthropic", image: true, tools: true, ready: true, reason: "", efforts: ["默认", "高"] },
  { id: "Local / Text-only example", label: "本地文本模型", provider: "Local", image: false, tools: false, ready: true, reason: "", efforts: ["默认"] },
  { id: "Provider / Unconfigured example", label: "未配置通道示例", provider: "Provider", image: true, tools: true, ready: false, reason: "未配置凭据", efforts: ["默认"] },
];
export const modelKeys = ["dialogue", "reasoningEffort", "mentalModel", "summary", "subagentPlanning", "subagentExecution", "vision"];
const slots = [["mentalModel", "心智模型"], ["summary", "摘要模型"], ["subagentPlanning", "子任务规划"], ["subagentExecution", "子任务执行"], ["vision", "视觉模型"]];
export function modelChanges(draft: Draft, saved: Draft) {
  return modelKeys.filter(key => draft[key] !== saved[key]).map(key => ({ key, label: key === "dialogue" ? "主模型" : key === "reasoningEffort" ? "思考方式" : slots.find(s => s[0] === key)?.[1] ?? key, before: String(saved[key]), after: String(draft[key]) }));
}
export function ModelSetupPreview({ draft, saved, onPatch }: { draft: Draft; saved: Draft; onPatch: (key: string, value: string) => void }) {
  const [slot, setSlot] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [showUnavailable, setShowUnavailable] = useState(false);
  const [changeNote, setChangeNote] = useState("");
  const selected = models.find(m => m.id === draft.dialogue) ?? models[0];
  const overrides = slots.filter(([key]) => draft[key] && draft[key] !== "沿用对话模型");
  const candidates = models.filter(m => (m.ready || showUnavailable) && [m.label, m.provider].some(v => v.toLowerCase().includes(query.toLowerCase())));
  const openPicker = (key: string) => { setSlot(key); setQuery(""); };
  const choose = (model: typeof models[number]) => {
    if (!slot || !model.ready || (slot === "vision" && !model.image) || (slot === "dialogue" && !model.tools)) return;
    onPatch(slot, model.id);
    if (slot === "dialogue" && !model.efforts.includes(String(draft.reasoningEffort))) {
      onPatch("reasoningEffort", "默认"); setChangeNote("思考强度已恢复默认，未保存。");
    } else setChangeNote("");
    setSlot(null);
  };
  function control(key: string, label: string) {
    const model = models.find(m => m.id === draft[key]);
    return <VPopover open={slot === key} onOpenChange={open => open ? openPicker(key) : setSlot(null)} align="end" side="bottom" sideOffset={8} aria-label={`${label}选项`} contentClassName="!w-[352px] !max-w-[calc(100vw-32px)] !rounded-lg !border-vui-border-subtle !p-2 !bg-vui-surface-panel !shadow-lg" trigger={<VButton contentLayout="plain" variant="secondary" className={`${flatControl} !w-full !justify-between !gap-3`} aria-label={`选择${label}`}><span className="truncate font-normal">{model?.label ?? "默认"}</span><span className="flex shrink-0 items-center gap-2">{model && <span className="text-xs text-vui-fg-tertiary">{model.provider}</span>}<ChevronDown size={14} className="text-vui-fg-tertiary"/></span></VButton>}>
      <div className="grid gap-2"><div className="relative"><VInput autoFocus aria-label="搜索模型" placeholder="搜索模型" className={`${flatControl} !pl-9`} value={query} onChange={e => setQuery(e.target.value)}/><Search size={14} className="pointer-events-none absolute left-3 top-3.5 text-vui-fg-tertiary"/></div><div className="grid max-h-[280px] gap-0.5 overflow-y-auto">{key !== "dialogue" && <VNativeButton className="flex min-h-11 w-full items-center justify-between rounded-md px-3 text-left text-sm hover:bg-vui-surface-toolbar" onClick={() => { onPatch(key, "沿用对话模型"); setSlot(null); }}>默认{!model && <Check size={14}/>}</VNativeButton>}{candidates.map(m => { const reason = !m.ready ? m.reason : key === "vision" && !m.image ? "不支持图像输入" : key === "dialogue" && !m.tools ? "不支持工具调用" : ""; return <VNativeButton key={m.id} title={reason || m.provider} aria-label={`${m.label} ${m.provider}`} disabled={Boolean(reason)} className={`flex min-h-11 w-full items-center justify-between gap-3 rounded-md px-3 py-2 text-left hover:bg-vui-surface-toolbar ${draft[key] === m.id ? "bg-vui-surface-toolbar" : ""}`} onClick={() => choose(m)}><span className="grid min-w-0 gap-0.5"><span className="truncate text-sm">{m.label}</span>{reason ? <span className="text-xs text-vui-fg-tertiary">{reason}</span> : <span className="text-xs text-vui-fg-tertiary">{m.provider}</span>}</span><span className="flex shrink-0 items-center gap-2 text-vui-fg-tertiary">{m.tools && <Wrench size={13} aria-label="工具调用"/>}{m.image && <Image size={13} aria-label="图像输入"/>}{draft[key] === m.id && <Check size={14} className="text-vui-fg-primary"/>}</span></VNativeButton>; })}{!candidates.length && <span className="px-3 py-4 text-xs text-vui-fg-tertiary">无匹配模型</span>}</div><div className="border-t border-vui-border-subtle px-2 pt-1"><VCheckbox className="!min-h-10 !text-xs" isSelected={showUnavailable} onChange={setShowUnavailable}>显示不可用模型</VCheckbox></div></div>
    </VPopover>;
  }
  return <section className="w-full min-w-0">
    <div className="flex items-center justify-between pb-5"><h2 className="m-0 text-[15px] font-semibold">主模型</h2>{draft.dialogue !== saved.dialogue && <span className="text-xs text-vui-fg-tertiary">未保存</span>}</div>
    <div className="grid grid-cols-[160px_minmax(0,1fr)] items-center gap-8 pb-4 max-sm:grid-cols-1 max-sm:gap-2"><span className="text-sm text-vui-fg-secondary">模型</span>{control("dialogue", "主模型")}</div>
    <div className="grid grid-cols-[160px_minmax(0,1fr)] items-center gap-8 pb-7 max-sm:grid-cols-1 max-sm:gap-2"><label htmlFor="model-setup-effort" className="text-sm text-vui-fg-secondary">思考强度</label><VSelect id="model-setup-effort" aria-label="思考强度" className={selectControl} selectedKey={String(draft.reasoningEffort)} options={selected.efforts.map(e => ({id:e,label:e === "默认" ? "模型默认" : e}))} onSelectionChange={key => key !== null && onPatch("reasoningEffort", String(key))}/></div>
    {changeNote && <p role="status" className="my-3 text-xs text-vui-fg-secondary">{changeNote}</p>}
    <details className="border-t border-vui-border-subtle pt-5"><summary className="cursor-pointer py-2 text-sm font-medium marker:text-vui-fg-tertiary">专用模型{overrides.length > 0 && <span className="ml-2 text-xs font-normal text-vui-fg-tertiary">{overrides.length}</span>}</summary><div className="grid gap-4 pt-4">{slots.map(([key, label]) => <div key={key} className="grid grid-cols-[160px_minmax(0,1fr)] items-center gap-8 max-sm:grid-cols-1 max-sm:gap-2"><span className="text-sm text-vui-fg-secondary">{label}</span>{control(key, label)}</div>)}</div></details>
  </section>;
}
