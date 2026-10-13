import { useState, type ReactNode } from "react";
import { Bot, ChevronRight, ExternalLink, Search, SunMoon, X } from "lucide-react";
import { VButton, VDialog, VInput, VNativeSelect, VTextarea, VCheckbox, VFieldRow, VListDetailPage, VSettingsFormPage } from "../../src/components/vui";
import { AgentPermissionPresetControl } from "../../src/components/vui/product/agent-management";
import type { AgentPermissionPreset } from "../../src/api/types";
import { createBundle, groupLabels, type Bundle, type SaveGroup } from "./fixtures";
import { ModelSetupPreview, modelChanges, modelKeys } from "./ModelSetupPreview";
import { flatControl, quietButton, primaryButton } from "./previewStyles";

type TabId = "models" | "basic" | "persona" | "task" | "ability" | "runtime" | "ops";
const tabs: Array<{ id: TabId; label: string }> = [
  { id: "models", label: "模型" }, { id: "basic", label: "基本" }, { id: "persona", label: "人物" },
  { id: "task", label: "任务" }, { id: "ability", label: "工具与记忆" }, { id: "runtime", label: "委派与监督" }, { id: "ops", label: "运维" },
];
const controlClass = flatControl;
function numericBounds(key: string): { min: number; max?: number } {
  if (key === "maxConcurrent") return { min: 0, max: 8 };
  if (key === "maxDepth") return { min: 0, max: 4 };
  if (key.endsWith("Threshold")) return { min: 1, max: 100 };
  return { min: ["maxCompressionsPerSession", "keepAiMessages"].includes(key) ? 0 : 1 };
}
function validNumber(key: string, value: string | boolean | string[]) {
  const n = Number(value), bounds = numericBounds(key);
  return String(value).trim() !== "" && Number.isInteger(n) && n >= bounds.min && (bounds.max === undefined || n <= bounds.max);
}
function Block({ title, note, children, actions }: { title: string; note?: string; children: ReactNode; actions?: ReactNode }) {
  return <section className="grid min-w-0 content-start gap-5"><div className="flex min-w-0 items-center justify-between gap-2"><h2 className="m-0 text-[15px] font-semibold">{title}</h2>{actions}</div><div className="grid min-w-0 gap-4">{children}</div></section>;
}
function Row({ label, children, note }: { label: string; children: ReactNode; note?: string }) {
  return <div className="grid min-w-0 grid-cols-[160px_minmax(0,1fr)] items-start gap-8 max-sm:grid-cols-1 max-sm:gap-2"><div className="pt-2.5 text-sm text-vui-fg-secondary max-sm:pt-0">{label}</div><div className="grid min-w-0 gap-1.5">{children}</div></div>;
}
export function App() {
  const [agent, setAgent] = useState("research");
  const [active, setActive] = useState<TabId>("models");
  const [drafts, setDrafts] = useState<Record<string, Bundle>>(() => ({ research: createBundle("research"), coding: createBundle("coding") }));
  const [saved, setSaved] = useState<Record<string, Bundle>>(() => ({ research: createBundle("research"), coding: createBundle("coding") }));
  const [search, setSearch] = useState("");
  const [idInputs, setIdInputs] = useState<Record<string, string>>({});
  const [notice, setNotice] = useState("");
  const [dialog, setDialog] = useState<string | null>(null);
  const [dark, setDark] = useState(false);
  const bundle = drafts[agent];
  const modelDirty = modelChanges(bundle.basic, saved[agent].basic).length > 0;
  const saveModels = () => { const patch = Object.fromEntries(modelKeys.map(key => [key, bundle.basic[key]])); setSaved(s => ({ ...s, [agent]: { ...s[agent], basic: { ...s[agent].basic, ...patch } } })); setNotice("已保存（预览）"); };
  const resetModels = () => { const patch = Object.fromEntries(modelKeys.map(key => [key, saved[agent].basic[key]])); setDrafts(d => ({ ...d, [agent]: { ...d[agent], basic: { ...d[agent].basic, ...patch } } })); setNotice(""); };
  const isDirty = (g: SaveGroup) => g === "basic" ? Object.keys(bundle.basic).filter(key => !modelKeys.includes(key)).some(key => bundle.basic[key] !== saved[agent].basic[key]) : JSON.stringify(bundle[g]) !== JSON.stringify(saved[agent][g]);
  const update = (g: SaveGroup, key: string, value: string | boolean | string[]) => { setDrafts(d => ({ ...d, [agent]: { ...d[agent], [g]: { ...d[agent][g], [key]: value, ...(g === "governance" && key === "reviewMode" && value !== "建议" ? { requiresReview: value === "强制" } : {}) } } })); setNotice(""); };
  const save = (g: SaveGroup) => { const persisted = structuredClone(bundle[g]); const pendingModels = Object.fromEntries(modelKeys.map(key => [key, bundle.basic[key]])); if (g === "basic") { for (const key of modelKeys) persisted[key] = saved[agent].basic[key]; const compressionKeys = Object.keys(bundle.basic).filter(key => !modelKeys.includes(key) && !["displayName", "status", "permissionPreset", "promptTemplateId", "toolPolicyId", "memoryPolicyId"].includes(key)); if (compressionKeys.some(key => bundle.basic[key] !== saved[agent].basic[key])) persisted.mode = "自定义"; } setSaved(s => ({ ...s, [agent]: { ...s[agent], [g]: persisted } })); setDrafts(d => ({ ...d, [agent]: { ...d[agent], [g]: { ...structuredClone(persisted), ...(g === "basic" ? pendingModels : {}) } } })); setNotice("已保存（预览）"); };
  const discard = (g: SaveGroup) => { setDrafts(d => ({ ...d, [agent]: { ...d[agent], [g]: { ...structuredClone(saved[agent][g]), ...(g === "basic" ? Object.fromEntries(modelKeys.map(key => [key, bundle.basic[key]])) : {}) } } })); if (g === "memory") setIdInputs(d => Object.fromEntries(Object.entries(d).filter(([key]) => !key.startsWith(agent + ":")))); setNotice(""); };
  const changeAgent = (id: string) => { setAgent(id); setNotice(""); };
  const value = (g: SaveGroup, key: string) => String(bundle[g][key] ?? "");
  const input = (g: SaveGroup, key: string, label: string, number = false) => <VInput aria-label={label} className={controlClass} type={number ? "number" : "text"} {...number ? numericBounds(key) : {}} aria-invalid={number && !validNumber(key, bundle[g][key]) ? true : undefined} value={value(g, key)} onChange={e => update(g, key, e.target.value)}/>;
  const select = (g: SaveGroup, key: string, label: string, options: string[]) => <VNativeSelect aria-label={label} className={controlClass} value={value(g, key)} onChange={e => update(g, key, e.target.value)}>{options.map(o => <option key={o}>{o}</option>)}</VNativeSelect>;
  const area = (g: SaveGroup, key: string, label: string) => <VTextarea aria-label={label} className={`${flatControl} !h-auto !min-h-24 !py-2.5 !leading-6 max-sm:!h-auto`} rows={3} value={value(g, key)} onChange={e => update(g, key, e.target.value)}/>;
  const checkbox = (g: SaveGroup, key: string, label: string) => <VCheckbox className={quietButton} isSelected={Boolean(bundle[g][key])} onChange={v => update(g, key, v)}>{label}</VCheckbox>;
  const idsField = (key: string, label: string) => {
    const options = key.includes("Groups") ? [{ id: "research-team", label: "研究团队" }, { id: "project-shared", label: "项目共享" }] : [{ id: "research-example", label: "研究资料库" }, { id: "engineering-example", label: "工程知识库" }];
    const ids = bundle.memory[key] as string[];
    const selection = idInputs[agent + ":" + key] ?? "";
    return <div className="grid gap-2"><div className="flex min-h-7 flex-wrap items-center gap-1">{ids.length ? ids.map(id => <VButton key={id} variant="ghost" title={id} aria-label={`从${label}移除${options.find(o => o.id === id)?.label ?? id}`} trailingIcon={<X size={12}/>} onClick={() => update("memory", key, ids.filter(item => item !== id))}>{options.find(o => o.id === id)?.label ?? id}</VButton>) : <span className="text-xs text-vui-fg-tertiary">未授权</span>}</div><div className="flex gap-2"><VNativeSelect aria-label={`选择${label}`} className={controlClass} value={selection} onChange={e => setIdInputs(d => ({ ...d, [agent + ":" + key]: e.target.value }))}><option value="">选择{key.includes("Groups") ? "共享组" : "知识库"}</option>{options.map(o => <option key={o.id} value={o.id} disabled={ids.includes(o.id)}>{o.label}</option>)}</VNativeSelect><VButton className={quietButton} aria-label={`添加${label}`} isDisabled={!selection || ids.includes(selection)} onClick={() => { update("memory", key, [...ids, selection]); setIdInputs(d => ({ ...d, [agent + ":" + key]: "" })); }}>添加</VButton></div></div>;
  };
  const validGroup = (g: SaveGroup) => g === "basic" ? Boolean(value(g, "displayName").trim()) && (value(g, "mode") !== "自定义" || ["maxTokenLimit", "maxCompressionsPerSession", "keepAiMessages", "lightThreshold", "standardThreshold", "deepThreshold", "emergencyThreshold", "lightSummaryChars", "standardSummaryChars", "deepSummaryChars", "emergencySummaryChars"].every(key => validNumber(key, bundle[g][key]))) : g !== "governance" || ["maxConcurrent", "maxDepth"].every(key => validNumber(key, bundle[g][key]));
  const actions = (g: SaveGroup) => <div className="flex items-center gap-2"><VButton className={quietButton} variant="secondary" isDisabled={!isDirty(g)} onClick={() => discard(g)}>还原</VButton><VButton className={primaryButton} variant="primary" isDisabled={!isDirty(g) || !validGroup(g)} disabledReason={!validGroup(g) ? "请检查名称或数值范围。" : undefined} aria-label={`保存${groupLabels[g]}`} onClick={() => save(g)}>保存</VButton></div>;
  const smallLink = (label: string, message: string) => <VButton variant="ghost" icon={<ExternalLink size={13}/>} className={quietButton} onClick={() => setDialog(message)}>{label}</VButton>;
  let content: ReactNode;
  if (active === "models") content = <ModelSetupPreview key={agent} draft={bundle.basic} saved={saved[agent].basic} onPatch={(key, value) => update("basic", key, value)}/>;
  else if (active === "basic") content = <>
      <Block title="基本信息">
        <Row label="显示名称">{input("basic", "displayName", "显示名称")}</Row>
        <Row label="提示词模板">{select("basic", "promptTemplateId", "提示词模板", ["研究任务 · 通用模板", "软件开发 · 通用模板", "通用对话模板"])}</Row>
      </Block>
      <Block title="权限与策略">
        <Row label="工具调用批准"><div className="[&_button>span]:!flex-1 [&_button>span]:!text-left [&_button]:!font-normal [&_button]:!text-sm [&_button]:!text-vui-fg-primary [&_button]:!gap-2 [&_button]:!h-10 [&_button]:!min-h-10 [&_button]:!rounded-md [&_button]:!shadow-none [&_button]:![background:var(--vui-surface-panel)] [&_button]:!border [&_button]:!border-vui-border-subtle max-sm:[&_button]:!h-11 max-sm:[&_button]:!min-h-11"><AgentPermissionPresetControl value={value("basic", "permissionPreset") as AgentPermissionPreset} lang="zh" surface="settings" disabled={false} pending={false} agentName={value("basic", "displayName")} onChange={v => update("basic", "permissionPreset", v)}/></div></Row>
        <Row label="工具策略">{select("basic", "toolPolicyId", "工具策略", ["研究工具策略", "开发工具策略"])}</Row>
        <Row label="记忆策略">{select("basic", "memoryPolicyId", "记忆策略", ["研究助手私有记忆", "开发助手私有记忆"])}</Row>
      </Block>
    <details className="group border-t border-vui-border-subtle pt-3"><summary className="cursor-pointer py-2 text-sm font-medium marker:text-vui-fg-tertiary">上下文压缩</summary><div className="grid gap-6 pt-4">
      <div className="grid gap-6"><Block title="上下文压缩"><Row label="配置来源" note="全局值在保存时形成快照，后续不会自动同步。">{select("basic", "mode", "配置来源", ["全局配置快照", "自定义"])}</Row>{value("basic", "mode") === "自定义" && <>{checkbox("basic", "enabled", "启用上下文压缩")}<Row label="Token 上限">{input("basic", "maxTokenLimit", "Token 上限", true)}</Row><Row label="压缩次数上限">{input("basic", "maxCompressionsPerSession", "压缩次数上限", true)}</Row></>}</Block></div>
      {value("basic", "mode") === "自定义" && <><Block title="分级压缩参数"><div className="grid grid-cols-2 gap-3 sm:grid-cols-4">{[["轻量", "light"], ["标准", "standard"], ["深度", "deep"], ["紧急", "emergency"]].map(([label, key]) => <div key={key} className="grid gap-3"><VFieldRow label={`${label}阈值 (%)`}>{input("basic", key + "Threshold", label + "阈值", true)}</VFieldRow><VFieldRow label={`${label}摘要字数`}>{input("basic", key + "SummaryChars", label + "摘要字数", true)}</VFieldRow></div>)}</div></Block><div className="grid gap-3 sm:grid-cols-3"><VFieldRow label="保留 AI 消息数">{input("basic", "keepAiMessages", "保留 AI 消息数", true)}</VFieldRow>{checkbox("basic", "preserveErrors", "保留错误信息")}{checkbox("basic", "extractKeyDecisions", "提取关键决策")}</div></>}
    </div></details>
  </>;
  else if (active === "persona") content = <>
    <Block title="专业与沟通"><Row label="专业领域">{input("persona", "expertise", "专业领域")}</Row><Row label="性格特征">{area("persona", "personality", "性格特征")}</Row><Row label="沟通风格">{area("persona", "communicationStyle", "沟通风格")}</Row><Row label="协作偏好">{area("persona", "collaborationPreference", "协作偏好")}</Row></Block>
    <Block title="背景"><Row label="背景经历">{area("persona", "background", "背景")}</Row></Block>
    <details className="border-t border-vui-border-subtle pt-3"><summary className="cursor-pointer py-2 text-sm">其他身份信息 <span className="text-xs text-vui-fg-tertiary">可选</span></summary><div className="grid gap-4 pt-3 sm:grid-cols-3">{[["性别", "gender"], ["年龄", "age"], ["称呼 / 代词", "pronouns"]].map(([label, key]) => <VFieldRow key={key} label={label}>{input("persona", key, label)}</VFieldRow>)}<VFieldRow className="col-span-full" label="身份备注">{area("persona", "identityNotes", "身份备注")}</VFieldRow></div></details>
  </>;
  else if (active === "task") content = <>
    <Block title="职责与范围"><Row label="任务使命">{area("task", "mission", "任务使命")}</Row><Row label="任务类型">{input("task", "taskTypes", "任务类型")}</Row><Row label="主要职责">{area("task", "responsibilities", "主要职责")}</Row></Block>
    <Block title="交付要求">{[["成功标准", "successCriteria"], ["交付物", "deliverables"], ["约束条件", "constraints"]].map(([label, key]) => <Row key={key} label={label}>{area("task", key, label)}</Row>)}</Block>
    <details className="border-t border-vui-border-subtle pt-3"><summary className="cursor-pointer py-2 text-sm font-medium">任务偏好与交接</summary><div className="grid gap-4 pt-4">{[["偏好任务", "preferredTasks"], ["避免任务", "avoidTasks"], ["交接说明", "handoffNotes"]].map(([label, key]) => <Row key={key} label={label}>{area("task", key, label)}</Row>)}</div></details>
  </>;
  else if (active === "ability") content = <>
    <Block title="工具" actions={smallLink("管理工具", "具体工具的启用、屏蔽与策略维护位于工具页，本预览仅展示当前绑定。") }><Row label="当前工具策略"><span className="py-2.5 text-sm">{String(saved[agent].basic.toolPolicyId)}</span></Row></Block>
    <Block title="记忆策略" note={`编辑当前绑定的「${String(saved[agent].basic.memoryPolicyId)}」。独立保存，不会同时保存基本配置。`}>
      <Row label="记忆">{checkbox("memory", "enabled", "启用")}</Row>
      {[["共享记忆读取组", "readSharedGroups"], ["共享记忆写入组", "writeSharedGroups"]].map(([label, key]) => <Row key={key} label={label}>{idsField(key, label)}</Row>)}
    </Block>
    <Block title="知识库权限">{[["读取", "readKnowledgeBaseIds"], ["提议", "proposeKnowledgeBaseIds"], ["审核", "reviewKnowledgeBaseIds"], ["评分", "rateKnowledgeBaseIds"]].map(([label, key]) => <Row key={key} label={label}>{idsField(key, label)}</Row>)}</Block>
  </>;
  else if (active === "runtime") content = <><Block title="委派"><Row label="子 Agent">{checkbox("governance", "allowSubagents", "允许委派")}</Row><Row label="唤醒消息">{checkbox("governance", "allowWakeMessages", "允许")}</Row><Row label="最大并发数">{input("governance", "maxConcurrent", "最大并发数", true)}</Row><Row label="最大委派深度">{input("governance", "maxDepth", "最大委派深度", true)}</Row><Row label="上下文模式"><div className="flex flex-wrap gap-3">{[["独立", "isolated"], ["继承", "fork"]].map(([label, mode]) => <VCheckbox key={mode} className={quietButton} isSelected={(bundle.governance.allowedContextModes as string[]).includes(mode)} onChange={selected => update("governance", "allowedContextModes", selected ? [...bundle.governance.allowedContextModes as string[], mode] : (bundle.governance.allowedContextModes as string[]).filter(m => m !== mode))}>{label}</VCheckbox>)}</div></Row></Block><Block title="监督"><Row label="监督">{checkbox("governance", "supervisionEnabled", "启用")}</Row><Row label="复核模式">{select("governance", "reviewMode", "复核模式", ["建议", "强制", "关闭"])}</Row><Row label="证据级别">{select("governance", "evidenceLevel", "证据级别", ["轻量", "标准", "严格"])}</Row><Row label="任务复核"><VCheckbox className={quietButton} isSelected={Boolean(bundle.governance.requiresReview)} isDisabled={value("governance", "reviewMode") !== "建议"} onChange={v => update("governance", "requiresReview", v)}>需要复核</VCheckbox></Row></Block></>;
  else content = <><Block title="运行维护"><Row label="健康检查"><div><VButton className={quietButton} onClick={() => setDialog("健康检查在此预览中不连接真实运行时。")}>检查</VButton></div></Row></Block><Block title="Agent 管理"><Row label="归档"><div><VButton className={quietButton} onClick={() => setDialog("预览操作：归档 Agent。未修改真实配置。")}>归档 Agent</VButton></div></Row><Row label="删除"><div><VButton className={`${quietButton} !text-vui-state-danger`} variant="danger" onClick={() => setDialog("预览操作：删除 Agent。未修改真实配置。")}>删除 Agent</VButton></div></Row></Block></>;
  const currentGroup: SaveGroup | null = active === "basic" || active === "persona" || active === "task" ? active : active === "ability" ? "memory" : active === "runtime" ? "governance" : null;
  const footer = active === "models" ? <div className="flex w-full max-w-[640px] flex-wrap items-center justify-between gap-2"><span role="status" className="text-xs text-vui-fg-tertiary">{notice || (modelDirty ? "未保存" : "已保存")}</span><div className="flex gap-2"><VButton className={quietButton} variant="secondary" isDisabled={!modelDirty} onClick={resetModels}>还原</VButton><VButton className={primaryButton} variant="primary" aria-label="保存模型配置" isDisabled={!modelDirty} onClick={saveModels}>保存</VButton></div></div> : currentGroup ? <div className="flex w-full max-w-[640px] flex-wrap items-center justify-between gap-2"><span role="status" className="text-xs text-vui-fg-tertiary">{notice || (isDirty(currentGroup) ? "未保存" : "已保存")}</span>{actions(currentGroup)}</div> : null;
  const sidebar = <aside className="flex h-full min-h-0 flex-col border-r border-vui-border-subtle bg-vui-surface-panel max-md:hidden"><div className="grid gap-3 p-4"><div className="flex items-center justify-between"><h1 className="m-0 text-sm font-semibold">Agent 管理</h1><span className="text-xs text-vui-fg-tertiary">2</span></div><div className="relative"><VInput aria-label="搜索 Agent" className={`${flatControl} !pl-8`} placeholder="搜索 Agent" value={search} onChange={e => setSearch(e.target.value)}/><Search size={14} className="pointer-events-none absolute left-2.5 top-3 text-vui-fg-tertiary"/></div></div><div className="grid content-start gap-1 px-2">{["research", "coding"].filter(id => String(saved[id].basic.displayName).includes(search)).map(id => <VButton key={id} contentLayout="plain" variant="ghost" className={`${quietButton} !w-full !h-auto !min-h-12 !gap-3 !justify-start !px-3 !py-2 ${agent === id ? "![background:var(--vui-surface-toolbar)]" : ""}`} aria-pressed={agent === id} onClick={() => changeAgent(id)}><Bot size={18} className="shrink-0"/><div className="grid min-w-0 gap-1 text-left"><strong className="truncate text-sm font-medium">{String(saved[id].basic.displayName)}</strong><span className="text-xs text-vui-fg-tertiary">{id === "research" ? "资料分析 · 核对证据" : "实现与代码审查"}</span></div></VButton>)}</div></aside>;
  const detail = <VSettingsFormPage ariaLabel="Agent 配置编辑器" title={String(saved[agent].basic.displayName)} meta={<span className="text-xs font-normal text-vui-fg-tertiary">活跃</span>}
    className="!flex !p-0 !gap-0 !bg-vui-surface-panel" headerClassName="px-10 pt-7 pb-4 max-sm:pt-4 [&_h1]:!text-xl [&_h1]:!font-semibold max-sm:px-4 [&_header]:!border-0 [&_header]:!bg-transparent [&_header]:!shadow-none [&_header]:!p-0 [&_header]:!backdrop-blur-none"
    toolbar={<div className="border-b border-vui-border-subtle px-10 max-sm:px-4"><nav aria-label="配置分类" className="flex min-w-0 items-center gap-6 overflow-x-auto [scrollbar-width:none] max-sm:gap-5">{tabs.map(t => <VButton key={t.id} contentLayout="plain" variant="ghost" className={`!h-11 !min-h-11 !shrink-0 !rounded-none !px-0 !border-x-0 !border-t-0 !border-b-2 !shadow-none ![background:transparent] ${active === t.id ? "!border-vui-fg-primary !text-vui-fg-primary !font-medium" : "!border-transparent !text-vui-fg-tertiary !font-normal"}`} aria-pressed={active === t.id} onClick={() => { setActive(t.id); setNotice(""); }}>{t.label}{t.id === "models" && modelDirty ? " ·" : ""}</VButton>)}</nav></div>}
    bodyClassName="!block px-10 py-7 max-sm:px-4 max-sm:py-5" footerClassName="!justify-start !px-10 !py-3 max-sm:!px-4 !bg-vui-surface-panel" footer={footer}>
    <div className="grid w-full max-w-[640px] gap-6 [&>section+section]:border-t [&>section+section]:border-vui-border-subtle [&>section+section]:pt-6">{content}</div>
  </VSettingsFormPage>;
  return <div className="flex h-dvh min-w-0 flex-col bg-vui-surface-workspace text-vui-fg-primary"><header className="flex shrink-0 flex-wrap items-center justify-between gap-1 border-b border-vui-border-subtle bg-vui-surface-panel px-4 py-1.5"><div className="flex items-center gap-2 text-sm"><span>工作台</span><ChevronRight size={13}/><strong className="font-medium">Agent</strong></div><div className="flex items-center gap-2"><span className="text-xs text-vui-fg-tertiary">预览 · 示例</span><VButton aria-label="切换主题" variant="ghost" className="!size-11 !p-0" icon={<SunMoon size={16}/>} onClick={() => { setDark(!dark); document.documentElement.dataset.theme = dark ? "light" : "dark"; }}/></div></header><div className="hidden shrink-0 px-4 py-2 max-md:block"><VNativeSelect aria-label="当前 Agent" className={controlClass} value={agent} onChange={e => changeAgent(e.target.value)}><option value="research">研究助手</option><option value="coding">开发助手</option></VNativeSelect></div><main className="min-h-0 min-w-0 flex-1"><VListDetailPage title="Agent 配置" hideHeader className="!p-0 !gap-0" columnsClassName="!grid-cols-[200px_minmax(0,1fr)] max-md:!grid-cols-1" workspaceClassName="!gap-0 max-md:[&>[data-vui=split-sidebar]]:!hidden" list={sidebar} detail={detail}/></main><VDialog open={dialog !== null} onOpenChange={o => !o && setDialog(null)} title="配置说明" description={dialog ?? ""} footer={<VButton onClick={() => setDialog(null)}>关闭</VButton>}/></div>;
}
