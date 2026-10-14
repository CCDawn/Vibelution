import { useMemo, useState, type ReactNode } from "react";
import { ArrowLeft, Bell, Box, Check, ChevronRight, CircleHelp, FlaskConical, GitBranch, Info, ListChecks, MoreHorizontal, RefreshCw, Search, Settings, ShieldCheck, Wrench, X } from "lucide-react";
import { VButton, VConfirmDialog, VDropdownMenu, VIconButton, VListDetailPage, VNativeButton, VNativeInput, VStateSurface, VStringSelect, VTabs, VWorkbenchFrame } from "../../src/components/vui";
import { agents, bundles, initialModes, tools, type Mode, type Tool } from "./fixtures";

const quiet = "!border-transparent !bg-none !bg-transparent !shadow-none text-vui-fg-secondary hover:!bg-vui-surface-row-hover";
const row = "flex min-w-0 w-full items-center gap-3 rounded-[6px] px-3 py-2.5 text-left text-vui-micro-13 hover:bg-vui-surface-row-hover";
const small = "text-vui-2xs text-vui-fg-tertiary";
const tabList = "!w-fit !border-0 !bg-transparent !p-0 !gap-1";
const tabTrigger = "!min-h-8 max-md:!min-h-11 !px-3 !rounded-[6px] !border-transparent !shadow-none !bg-none data-[state=active]:!bg-[var(--vui-selection-bg)]";

function Disclosure({ title, subtitle, children, open = false }: { title: string; subtitle?: string; children: ReactNode; open?: boolean }) {
  return <details className="group border-t border-vui-border-subtle py-3" open={open || undefined}><summary className="flex min-h-8 cursor-pointer list-none items-center gap-2 text-vui-micro-13 font-medium [&::-webkit-details-marker]:hidden"><ChevronRight size={14} className="shrink-0 text-vui-fg-tertiary group-open:rotate-90"/>{title}{subtitle && <span className={`ml-auto text-right font-normal ${small}`}>{subtitle}</span>}</summary><div className="pt-3 text-vui-micro-13 leading-6">{children}</div></details>;
}

export function App() {
  const [view, setView] = useState(new URLSearchParams(window.location.search).get("view") === "policy" ? "policy" : "library");
  const [activeName, setActiveName] = useState(tools[0].name);
  const [bundle, setBundle] = useState(bundles[9]);
  const [search, setSearch] = useState("");
  const [policySearch, setPolicySearch] = useState("");
  const [filter, setFilter] = useState("all");
  const [agent, setAgent] = useState(agents[0].value);
  const [scope, setScope] = useState("主 Agent");
  const [batch, setBatch] = useState(false);
  const [selected, setSelected] = useState<string[]>([]);
  const [modes, setModes] = useState<Record<string, Mode>>(initialModes);
  const [saved, setSaved] = useState<Record<string, Mode>>(initialModes);
  const [shared, setShared] = useState(false);
  const [savedShared, setSavedShared] = useState(false);
  const [preferred, setPreferred] = useState<string[]>([]);
  const [savedPreferred, setSavedPreferred] = useState<string[]>([]);
  const [enabled, setEnabled] = useState(true);
  const [removed, setRemoved] = useState(false);
  const [result, setResult] = useState("");
  const [notice, setNotice] = useState("");
  const [confirmation, setConfirmation] = useState<"save" | "delete" | "bulk-delete" | null>(null);
  const available = tools.filter(t => !(removed && t.source === "生成"));
  const active = available.find(t => t.name === activeName) ?? available[0];
  const visible = useMemo(() => available.filter(t => (filter === "all" || (filter === "builtin" && t.source === "内置") || (filter === "generated" && t.source === "生成") || (filter === "llm" && t.llm) || (filter === "enabled" && t.source === "生成" && enabled)) && `${t.name} ${t.summary} ${t.bundle}`.toLowerCase().includes(search.toLowerCase())), [available, filter, search, enabled]);
  const dirty = JSON.stringify(modes) !== JSON.stringify(saved) || shared !== savedShared || JSON.stringify(preferred) !== JSON.stringify(savedPreferred);
  const allowedCount = Object.values(modes).filter(m => m === "allowed").length;
  const blockedCount = Object.values(modes).filter(m => m === "blocked").length;
  const policyTools = available.filter(t => policySearch ? `${t.name} ${t.summary} ${t.bundle}`.toLowerCase().includes(policySearch.toLowerCase()) : t.bundle === bundle);
  const inform = (text: string) => setNotice(text);
  const selectTool = (tool: Tool) => {setActiveName(tool.name); setResult("");};
  const reset = () => {setModes(saved);setShared(savedShared);setPreferred(savedPreferred);setNotice("");};
  const applyBundle = (replace: boolean) => {
    const names = available.filter(t => t.bundle === bundle).map(t => t.name);
    if (!names.length) {inform("此工具包未收录预览样例。正式页使用完整注册表。");return;}
    setModes(current => ({...(replace ? {} : current), ...Object.fromEntries(names.map(n => [n, "allowed" as Mode]))}));
    setPreferred(current => replace ? names.slice(0, 2) : [...new Set([...current,...names.slice(0,2)])]);
    inform(`${replace ? "替换" : "追加"}已在本地草稿中模拟；保存前仍需验证。`);
  };
  const batchAction = (action: "启用" | "停用") => {const generated = selected.some(n => tools.find(t => t.name === n)?.source === "生成"); if(generated)setEnabled(action === "启用");inform(`模拟${action}：${generated ? 1 : 0} 个生成工具；内置工具受保护，自动跳过。`);};
  const confirm = () => {
    if(confirmation === "save"){setSaved(modes);setSavedShared(shared);setSavedPreferred(preferred);inform("示例配置已保存到本页内存。没有修改真实 Agent 权限。");}
    else {if(confirmation === "delete" || selected.includes("generated_summary_example"))setRemoved(true);setSelected([]);inform("模拟删除已完成；内置工具受保护。刷新预览可恢复示例。");}
    setConfirmation(null);
  };

  const libraryRail = <aside className="flex h-full min-h-0 flex-col px-2 pb-2 pt-3" aria-label="工具注册表">
    <div className="mb-3 flex items-center justify-between px-2"><h1 className="text-vui-xs font-medium">工具库 <span className={`ml-2 font-normal ${small}`}>{available.length}</span></h1><VIconButton label={batch ? "退出批量选择" : "批量选择"} icon={<ListChecks size={16}/>} className={quiet} onPress={() => {setBatch(!batch);setSelected([]);}}/></div>
    <label className="mx-1 mb-2 flex items-center gap-2 rounded-[6px] border border-vui-border-subtle bg-vui-surface-chat px-2"><Search size={14} className="text-vui-fg-tertiary shrink-0"/><VNativeInput aria-label="搜索工具" placeholder="搜索工具" value={search} onChange={e => setSearch(e.target.value)} className="!min-h-8 !w-full !border-0 !bg-transparent !shadow-none !px-0 !text-vui-micro-13"/></label>
    <div className="mx-1 mb-3"><VStringSelect ariaLabel="工具筛选" value={filter} onValueChange={setFilter} options={[{value:"all",label:"全部工具"},{value:"builtin",label:"内置工具"},{value:"generated",label:"生成工具"},{value:"llm",label:"LLM 可见"},{value:"enabled",label:"已启用的生成工具"}]}/></div>
    {batch && <div className="mb-2 flex items-center justify-between px-2 text-vui-2xs"><span>已选 {selected.length}</span><VButton variant="ghost" density="compact" className={quiet} onPress={() => setSelected(selected.length === visible.length ? [] : visible.map(t => t.name))}>{selected.length === visible.length ? "清除选择" : "选择当前列表"}</VButton></div>}
    <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain">
      {bundles.filter(b => visible.some(t => t.bundle === b)).map(b => <section key={b}><h2 className="flex items-center justify-between px-3 pb-1 pt-4 text-vui-2xs font-normal text-vui-fg-tertiary"><span>{b}</span><span>{visible.filter(t => t.bundle === b).length}</span></h2>{visible.filter(t => t.bundle === b).map(t => <div key={t.name} className="flex items-center gap-1">{batch && <VNativeInput type="checkbox" aria-label={`选择 ${t.name}`} checked={selected.includes(t.name)} onChange={e => setSelected(e.target.checked ? [...selected,t.name] : selected.filter(n => n!==t.name))} className="ml-1 shrink-0"/>}<VNativeButton onClick={() => selectTool(t)} aria-pressed={active.name===t.name} className={`${row} !items-start ${active.name===t.name ? "bg-[var(--vui-selection-bg)]" : ""}`}><Wrench size={15} className="mt-1 shrink-0 text-vui-fg-secondary" strokeWidth={1.5}/><span className="min-w-0 flex-1"><strong className="block break-all text-vui-micro-13 font-medium leading-5">{t.name}</strong><span className={`mt-1 block ${small}`}>{t.risk} · {t.source === "生成" ? enabled ? "已启用" : "已停用" : "内置"}</span></span></VNativeButton></div>)}</section>)}
      {!visible.length && <VStateSurface tone="empty" title="没有匹配的工具" className="!border-0 !bg-transparent !shadow-none"/>}
    </div>
    {selected.length>0 && <div className="mt-2 flex shrink-0 flex-wrap items-center gap-1 border-t border-vui-border-subtle pt-2" aria-label="批量操作"><VButton density="compact" onPress={() => batchAction("启用")}>启用</VButton><VButton density="compact" onPress={() => batchAction("停用")}>停用</VButton><VButton density="compact" variant="ghost" onPress={() => setConfirmation("bulk-delete")}>删除</VButton><VIconButton label="清除选择" density="compact" icon={<X size={14}/>} className={`${quiet} ml-auto`} onPress={() => setSelected([])}/></div>}
  </aside>;

  const policyRail = <aside className="flex h-full min-h-0 flex-col px-2 pt-4" aria-label="工具包列表"><h1 className="mb-4 px-3 text-vui-xs font-medium">工具包</h1><div className="min-h-0 flex-1 overflow-y-auto pb-3">{bundles.map(b => <VNativeButton key={b} className={`${row} !min-h-10 ${b === bundle ? "bg-[var(--vui-selection-bg)]" : ""}`} aria-pressed={b===bundle} onClick={() => {setBundle(b);setPolicySearch("");}}><Box size={16} strokeWidth={1.5} className="shrink-0 text-vui-fg-tertiary"/><span className="min-w-0 flex-1 break-words">{b}</span><span className={small}>{available.filter(t => t.bundle===b).length || "—"}</span></VNativeButton>)}</div><div className={`border-t border-vui-border-subtle px-3 py-3 leading-5 ${small}`}>选择工具包，调整当前 Agent 的权限。</div></aside>;

  const context = <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-vui-border-subtle px-5 py-3 max-sm:px-4"><label className={`flex min-w-0 items-center gap-2 ${small}`}><span className="shrink-0">配置 Agent</span><VStringSelect className="!w-[250px] !shrink-0 max-sm:!w-[230px]" ariaLabel="配置 Agent" value={agent} options={agents} onValueChange={next => {setAgent(next);setModes(initialModes);setSaved(initialModes);setPreferred([]);setSavedPreferred([]);setShared(false);setSavedShared(false);setNotice("已切换示例 Agent。真实配置未连接。");}}/></label><label className={`flex items-center gap-2 whitespace-nowrap ${small}`}><span>Agent 范围</span><VStringSelect className="!w-[128px] !shrink-0" ariaLabel="Agent 范围" value={scope} onValueChange={setScope} options={["主 Agent","全部 Agent"].map(label=>({value:label,label}))}/></label></div>;

  const detail = <div className="flex h-full min-h-0 flex-col">
    <div className="flex min-h-12 shrink-0 flex-wrap items-center justify-between gap-2 px-4 py-2"><VTabs aria-label="工具管理视图" value={view} onValueChange={next => {setView(next);setNotice("");}} items={[{id:"library",label:"工具库"},{id:"policy",label:"Agent 工具配置"}]} listClassName={tabList} triggerClassName={tabTrigger}/><span className={`${small} px-1`}>{view === "policy" ? dirty ? "未保存" : "已同步" : "注册表"}</span></div>
    <div className="hidden shrink-0 px-4 pb-3 max-md:block"><VStringSelect ariaLabel={view === "library" ? "当前工具" : "当前工具包"} value={view === "library" ? active.name : bundle} onValueChange={value => {if(view === "library"){setActiveName(value);setResult("");}else{setBundle(value);setPolicySearch("");}}} options={view === "library" ? available.map(t => ({value:t.name,label:t.name})) : bundles.map(b=>({value:b,label:b}))}/></div>
    {context}
    {notice && <div role="status" className="flex shrink-0 items-start gap-2 border-b border-vui-border-subtle bg-vui-surface-row px-5 py-2 text-vui-2xs leading-5"><Info size={14} className="mt-0.5 shrink-0"/><span className="flex-1">{notice}</span><VIconButton label="关闭提示" density="compact" className={quiet} icon={<X size={13}/>} onPress={() => setNotice("")}/></div>}
    {view === "library" ? <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-6 py-6 max-sm:px-4 max-sm:py-4">
      <div className="mx-auto max-w-[880px]">
        <header className="mb-5 flex items-start justify-between gap-3"><div className="min-w-0"><p className={`mb-2 ${small}`}>{active.bundle} <span className="mx-1">/</span> {active.source}</p><h2 className="break-all text-vui-title font-medium leading-7">{active.name}</h2><p className="mt-3 max-w-[64ch] text-vui-micro-13 leading-6 text-vui-fg-secondary">{active.summary}</p></div><VDropdownMenu aria-label="工具操作" trigger={<VIconButton label="工具操作" className={quiet} icon={<MoreHorizontal size={18}/>}/>} items={[{id:"toggle",label:enabled ? "停用工具" : "启用工具",disabled:active.source === "内置",onSelect:()=>{setEnabled(!enabled);inform("仅模拟生成工具状态变更。");}},{id:"delete",label:"删除工具",disabled:active.source === "内置",danger:true,onSelect:()=>setConfirmation("delete")}]}/></header>
        <div className="flex flex-wrap items-center gap-x-6 gap-y-2 pb-5 text-vui-2xs"><span className="flex items-center gap-1.5"><span className={`size-1.5 rounded-full ${active.source === "生成" && !enabled ? "bg-vui-fg-tertiary" : "bg-[var(--success)]"}`}/>{active.source === "生成" ? enabled ? "已启用" : "已停用" : "活跃"}</span><span className="flex items-center gap-1.5"><ShieldCheck size={14} strokeWidth={1.5}/>{active.risk}</span><span className="text-vui-fg-secondary">{active.source === "内置" ? "内置工具受保护" : "已验证的生成工具示例"}</span></div>
        <dl className="grid grid-cols-2 gap-x-8 gap-y-4 border-y border-vui-border-subtle py-5 text-vui-micro-13 max-sm:grid-cols-1">
          {[["当前范围可见","是"],["当前范围可调用","是"],["LLM 可见",active.llm ? "是" : "否"],["Agent 明确授权",(saved[active.name] ?? "inherited") === "allowed" ? "允许" : (saved[active.name] ?? "inherited") === "blocked" ? "禁用" : "未允许"]].map(([label,value])=><div key={label} className="flex min-w-0 items-center justify-between gap-2"><dt className="text-vui-fg-secondary">{label}</dt><dd className="font-medium">{value}</dd></div>)}
        </dl>
        <section className="py-5"><div className="mb-3 flex items-center justify-between gap-3"><h3 className="text-vui-xs font-medium">工具测试</h3><VButton variant="secondary" icon={<FlaskConical size={14}/>} onPress={() => setResult(active.safeTest ? "模拟测试完成。参数解析通过；未发生真实调用。" : "安全策略阻塞：不在浏览器安全测试 allow-list，未发生真实调用。")}>测试工具</VButton></div><p className="text-vui-micro-13 leading-6 text-vui-fg-secondary">{active.safeTest ? "模拟调用可用。测试使用当前 Agent 已保存的 ToolPolicy。" : "安全策略阻塞。此工具不在浏览器安全测试 allow-list。"}</p><div className={`mt-3 flex flex-wrap gap-x-5 gap-y-2 ${small}`}><span>真实调用：否</span><span>模拟调用：{active.safeTest ? "是" : "否"}</span><span>测试权限：{saved[active.name] === "allowed" ? "允许" : "未允许"}</span></div>{result && <p role="status" className="mt-4 flex items-start gap-2 rounded-[6px] bg-vui-surface-row px-3 py-2 text-vui-micro-13 leading-6"><Info size={15} className="mt-1 shrink-0"/>{result}</p>}</section>
        {active.name === "image2" && <Disclosure title="image2 工具模型" subtitle="当前模型与连接详情" open><VStringSelect ariaLabel="image2 工具模型" value="example" onValueChange={() => inform("模型切换仅为示例。")} options={[{value:"example",label:"当前配置模型 · 示例"}]}/><p className={`mt-2 ${small}`}>正式页保留模型选择、连接详情、保存与错误状态。</p></Disclosure>}
        {active.name === "web_search_tool" && <Disclosure title="搜索依赖状态" subtitle="token 服务与连接详情" open><p>本预览不连接 token 服务。正式页保留健康检查、服务地址、诊断与重试。</p></Disclosure>}
        <Disclosure title="参数 schema" subtitle="查看原始参数"><pre className="overflow-x-auto rounded-[6px] bg-vui-surface-row p-3 text-vui-2xs leading-6">{JSON.stringify({type:"object",properties:active.args},null,2)}</pre></Disclosure>
        <Disclosure title="测试参数与结果详情" subtitle="参数、策略、兼容性"><dl className="grid gap-3"><div>ToolPolicy：{agent} · {scope}</div><div>策略：{active.safeTest ? "模拟测试" : "安全策略阻塞"}</div><div>Agent 消息类型、工具调用、参数解析和结果预览在测试后展示。</div></dl><pre className="mt-3 overflow-x-auto rounded-[6px] bg-vui-surface-row p-3 text-vui-2xs">{JSON.stringify(active.args,null,2)}</pre></Disclosure>
        <Disclosure title="Manifest 与管理操作" subtitle={active.source === "内置" ? "内置工具受保护" : "生成工具可管理"}><dl className="mb-4 grid gap-2"><div>来源：{active.source}</div><div>验证：已验证 · 示例</div><div>可删除：{active.source === "内置" ? "否，Built-in tools are protected by the agent runtime." : "是"}</div></dl><div className="flex flex-wrap gap-2"><VButton isDisabled={active.source === "内置"} disabledReason="内置工具受保护" onPress={() => setEnabled(!enabled)}>{enabled ? "停用" : "启用"}</VButton><VButton variant="danger" isDisabled={active.source === "内置"} disabledReason="内置工具受保护" onPress={() => setConfirmation("delete")}>删除工具</VButton></div></Disclosure>
      </div>
    </div> : <>
      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-6 py-5 max-sm:px-4">
        <div className="mb-4 flex flex-wrap items-center gap-x-5 gap-y-2 text-vui-micro-13"><span>允许 <strong className="font-medium">{allowedCount}</strong></span><span className="text-vui-fg-secondary">优先 {preferred.length}</span><span className="text-vui-fg-secondary">禁用 {blockedCount}</span><span className={small}>配置作用于后续回合</span></div>
        <div className="mb-5 flex flex-wrap items-start justify-between gap-3"><div><h2 className="text-vui-lg font-medium">{policySearch ? "搜索结果" : bundle}</h2><p className={`mt-2 ${small}`}>{policyTools.length} 个示例工具 · {policyTools.filter(t=>t.risk==="高风险").length} 个高风险 · {policyTools.filter(t=>t.risk==="高风险").length} 个需显式授权</p></div><div className="flex gap-2"><VButton onPress={() => applyBundle(false)}>追加</VButton><VButton onPress={() => applyBundle(true)}>替换</VButton></div></div>
        <label className="mb-3 flex items-center gap-2 rounded-[6px] border border-vui-border-subtle px-3"><Search size={15} className="shrink-0 text-vui-fg-tertiary"/><VNativeInput aria-label="搜索可分配工具" placeholder="搜索可分配工具" value={policySearch} onChange={e=>setPolicySearch(e.target.value)} className="!min-h-9 !w-full !border-0 !bg-transparent !shadow-none !px-0 !text-vui-micro-13"/></label>
        <div className={`flex items-center justify-between px-1 py-2 ${small}`}><span>工具 / 来源</span><span>权限</span></div>
        {policyTools.map(t=><div key={t.name} className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-t border-vui-border-subtle py-3"><div className="min-w-0 flex-1 basis-[200px]"><h3 className="break-all text-vui-micro-13 font-medium">{t.name}</h3><p className={`mt-1 ${small}`}>{t.source} · {t.risk}{t.risk==="高风险" ? " · 需显式授权" : ""}{preferred.includes(t.name) ? " · 优先" : ""}</p><p className="mt-2 text-vui-2xs leading-5 text-vui-fg-secondary">{t.summary}</p></div><VTabs aria-label={`${t.name} 权限`} value={modes[t.name] ?? "inherited"} onValueChange={mode=>{setModes(current=>({...current,[t.name]:mode as Mode}));setNotice("");}} items={[{id:"inherited",label:"未允许"},{id:"allowed",label:"允许"},{id:"blocked",label:"禁用"}]} listClassName="!w-fit" triggerClassName="!min-h-8 max-md:!min-h-11 !px-3"/></div>)}
        {!policyTools.length && <VStateSurface tone="empty" title={policySearch ? "没有匹配的工具" : "此工具包未收录预览样例"} className="!border-0 !bg-transparent !shadow-none"><p>正式页保留完整工具包与工具注册表。</p></VStateSurface>}
        <Disclosure title="工作空间写入边界" subtitle={shared ? "私人 + 共享" : "仅私人"}><div className="flex flex-wrap gap-6"><label className="flex items-center gap-2"><VNativeInput type="checkbox" checked disabled/>私人工作区</label><label className="flex items-center gap-2"><VNativeInput type="checkbox" checked={shared} onChange={e=>setShared(e.target.checked)}/>共享资料区</label></div></Disclosure>
        <Disclosure title="权限摘要" subtitle="统计与生效边界"><div className="grid grid-cols-2 gap-3 max-sm:grid-cols-1"><span>未允许：{available.length-allowedCount-blockedCount}</span><span>高风险允许：{available.filter(t=>t.risk==="高风险" && modes[t.name]==="allowed").length}</span><span>明确允许：{allowedCount}</span><span>需显式授权：{available.filter(t=>t.risk==="高风险" && modes[t.name]==="allowed").length}</span><span>当前范围可见：{available.length}</span><span>当前范围受阻：0（示例）</span></div><p className="mt-4 text-vui-fg-secondary">范围可调用数量与 Agent 明确授权分别判断；正式保存使用服务端生效预览和确认。</p></Disclosure>
      </div>
      <footer className="flex shrink-0 flex-wrap items-center justify-between gap-2 border-t border-vui-border-subtle px-5 py-3 max-sm:px-4"><span className={`flex items-center gap-1.5 ${small}`}><Check size={14}/>{dirty ? "草稿有变更" : "配置已同步"}</span><div className="flex flex-wrap gap-2"><VButton variant="ghost" isDisabled={!dirty} onPress={reset}>重置草稿</VButton><VButton onPress={()=>inform(`模拟生效预览：允许 ${allowedCount}，禁用 ${blockedCount}，写入边界${shared ? "私人 + 共享" : "仅私人"}。正式结果由服务端计算。`)}>验证并预览</VButton><VButton variant="primary" isDisabled={!dirty} onPress={()=>setConfirmation("save")}>保存工具配置</VButton></div></footer>
    </>}
  </div>;

  return <div className="flex h-dvh min-h-0 min-w-0 flex-col overflow-hidden bg-vui-surface-rail text-vui-fg-primary max-md:[&_[data-vui=select]]:!min-h-11 max-md:[&_button]:!min-h-11 max-md:[&_input:not([type=checkbox])]:!min-h-11">
    <header className="flex h-11 shrink-0 items-center gap-2 px-2"><VIconButton label="返回" icon={<ArrowLeft size={16}/>} className={quiet} onPress={()=>inform("设计预览仅包含工具管理。")}/><nav aria-label="主导航" className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto">{["对话","智能体","团队","进化","记忆库","Agent 管理"].map(label=><VButton key={label} variant="ghost" className={`${quiet} shrink-0 ${label === "Agent 管理" ? "!bg-[var(--vui-selection-bg)]" : ""}`} onPress={()=>inform("设计预览仅包含工具管理，其他导航在正式工作台中保留。")}>{label}</VButton>)}</nav><span className={`mr-2 whitespace-nowrap max-md:hidden ${small}`}>设计预览 · 模拟数据</span><div className="flex items-center gap-1 max-md:hidden"><VIconButton label="变更" icon={<GitBranch size={16}/>} className={quiet}/><VIconButton label="通知" icon={<Bell size={16}/>} className={quiet}/><VIconButton label="设置" icon={<Settings size={16}/>} className={quiet}/></div></header>
    <div className="flex min-h-11 shrink-0 items-center justify-between gap-2 px-4"><nav className="flex gap-1" aria-label="Agent 管理导航">{["Agent","提示词","工具","技能"].map(label=><VButton key={label} variant="ghost" className={`${quiet} !min-h-8 ${label === "工具" ? "!bg-[var(--vui-selection-bg)] !text-vui-fg-primary" : ""}`} onPress={()=>inform("此预览只整理工具页面。")}>{label}</VButton>)}</nav><div className="flex items-center gap-1"><span className={`mr-2 md:hidden ${small}`}>模拟数据</span><VIconButton label="预览说明" icon={<CircleHelp size={16}/>} className={quiet} onPress={()=>inform("工具标识取自正式页面；仅展示部分工具样例，权限、测试、状态与保存均为模拟。")}/><VIconButton label="刷新预览" icon={<RefreshCw size={16}/>} className={quiet} onPress={()=>{reset();setRemoved(false);setEnabled(true);setResult("");inform("预览已恢复。未请求正式接口。");}}/></div></div>
    <VWorkbenchFrame><VListDetailPage ariaLabel="工具管理设计预览" hideHeader title="工具管理" className="!p-0 !gap-0" workspaceClassName="!gap-0 max-md:[&>[data-vui=split-sidebar]]:!hidden" columnsClassName="grid-cols-[304px_minmax(0,1fr)] max-md:grid-cols-1" list={<div className="h-full max-md:!h-auto max-md:max-h-[200px]">{view === "library" ? libraryRail : policyRail}</div>} detail={detail}/></VWorkbenchFrame>
    <VConfirmDialog open={confirmation!==null} onOpenChange={open=>!open&&setConfirmation(null)} title={confirmation === "save" ? "确认工具能力变更 · 模拟" : "确认删除 · 模拟"} description={confirmation === "save" ? "正式配置会影响当前 Agent 后续回合的工具可见性与执行权限。本预览仅保存内存中的示例草稿。" : "仅移除预览中的生成工具示例；内置工具自动跳过。刷新可恢复，不调用真实删除接口。"} cancelLabel="取消" confirmLabel={confirmation === "save" ? "确认保存示例" : "确认模拟删除"} onConfirm={confirm}/>
  </div>;
}
