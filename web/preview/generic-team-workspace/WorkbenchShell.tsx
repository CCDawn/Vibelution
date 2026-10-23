import { useState, type ReactNode } from "react";
import { ArrowLeft, ArrowRight, Bot, Check, ChevronDown, FileText, GitBranch, LayoutTemplate, Plus, Play, Save, Settings2, Square, Users } from "lucide-react";
import { VButton, VCanvasWorkbenchPage, VIconButton, VNativeButton, VTabs } from "../../src/components/vui";
import { WORKBENCH_LAYOUT_IDS } from "../../src/components/layout/workbenchLayoutIds";
import { FlowEditor } from "./FlowEditor";
import { EXAMPLE_FLOWS, MEMBERS, type Flow, type Run } from "./fixtures";

type Props = {
  flows: Flow[]; flow?: Flow; run?: Run; runs: Run[]; mode: "design" | "run";
  selectedId: string; dirty: boolean; inspector: ReactNode; notice: string;
  inspectorOpen: boolean; onInspectorOpen: (open: boolean) => void;
  onMode: (mode: "design" | "run") => void; onFlow: (id: string) => void;
  onStep: (id: string) => void; onRun: (id: string) => void;
  onSave: () => void; onStart: () => void; onStop: () => void;
  onCreate: () => void; onTemplate: (id: string) => void; onAddStep: () => void; onMembers: () => void;
  onArtifact: () => void; onDismiss: () => void; onScene: (scene: string) => void;
};
const primary = "!h-8 !min-h-8 !rounded-md !px-3 !text-[13px]";
const quiet = "!h-8 !min-h-8 !border-transparent !text-[var(--fg-secondary)] !text-[13px]";
const statusLabel = { running: "正在执行", waiting: "需要你确认", completed: "已完成", failed: "执行失败", stopped: "已停止" };

export function WorkbenchShell(props: Props) {
  const [leftTab, setLeftTab] = useState("flows");
  const [bottomTab, setBottomTab] = useState("messages");
  const [railOpen, setRailOpen] = useState(false);
  const { flow, run, mode } = props;
  const active = run?.status === "running" || run?.status === "waiting";
  const currentFlow = mode === "run" && run ? run.flow : flow;
  const selectStep = (id: string) => { props.onStep(id); props.onInspectorOpen(true); };
  const visibleFlows = flow ? props.flows : [];

  const rail = <div className="flex h-full min-h-0 flex-col bg-[var(--vui-surface-rail)]">
    <div className="flex h-[52px] shrink-0 items-center border-b border-[var(--vui-border-subtle)] px-3">
      <VButton variant="ghost" contentLayout="plain" className="!h-9 !w-full !justify-start !gap-2.5 !border-transparent !px-1.5" aria-label="查看团队成员" onClick={props.onMembers}>
        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-[var(--vui-status-info-bg)] text-[var(--accent-cool)]"><Users size={15}/></span>
        <span className="min-w-0 flex-1 truncate text-left text-[13px] font-semibold">AI 科研团队</span><ChevronDown size={13} className="text-[var(--fg-tertiary)]"/>
      </VButton>
    </div>
    <div className="px-3 pt-4"><VTabs aria-label="工作区导航" value={leftTab} onValueChange={setLeftTab} items={[{ id: "flows", label: "流程" }, { id: "members", label: "成员" }]} listClassName="!h-8 !w-full !border-0 !bg-[var(--vui-surface-row)] !p-0.5" triggerClassName="!h-7 !min-h-7 !flex-1 !py-0 !text-xs data-[state=active]:!text-[var(--fg-primary)]"/></div>
    <div className="min-h-0 flex-1 overflow-auto px-2.5 pb-3 pt-4">
      {leftTab === "flows" ? <>
        <div className="mb-2 flex items-center justify-between px-2"><span className="text-[11px] font-medium text-[var(--fg-tertiary)]">我的流程 <span className="ml-1.5">{visibleFlows.length}</span></span><VIconButton label="新建流程" icon={<Plus size={14}/>} variant="ghost" className="!h-7 !min-h-7 !w-7 !border-transparent" onClick={() => { setRailOpen(false); props.onCreate(); }}/></div>
        {visibleFlows.length ? <div className="grid gap-1.5">{visibleFlows.map(item => <VNativeButton key={item.id} aria-pressed={flow?.id === item.id} onClick={() => { props.onFlow(item.id); setRailOpen(false); }} className={"flex w-full items-start gap-2.5 rounded-lg border px-3 py-3 text-left transition-colors " + (flow?.id === item.id ? "border-[var(--vui-status-info-bg)] bg-[var(--vui-status-info-bg)] text-[var(--accent-cool)]" : "border-transparent hover:bg-[var(--vui-surface-row-hover)]")}>
          <GitBranch size={15} className="mt-0.5 shrink-0"/><span className="min-w-0"><span className="block truncate text-xs font-medium leading-5">{item.name}</span><span className="mt-0.5 block text-[11px] text-[var(--fg-tertiary)]">{item.steps.length} 个步骤 · {item.fields.length} 个输入</span></span>
        </VNativeButton>)}</div> : <p className="px-2 pt-1 text-xs leading-6 text-[var(--fg-tertiary)]">还没有流程<br/>从右侧选择模板开始。</p>}
      </> : <div className="grid gap-1">{MEMBERS.map(member => <VNativeButton key={member.id} className="flex w-full items-center gap-2.5 rounded-lg p-2 text-left hover:bg-[var(--vui-surface-row-hover)]" onClick={props.onMembers}><span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[var(--vui-surface-row)] text-xs text-[var(--fg-secondary)]">{member.initial}</span><span className="min-w-0"><span className="block text-xs font-medium">{member.name}</span><span className="block truncate text-[11px] leading-5 text-[var(--fg-tertiary)]">{member.detail}</span></span></VNativeButton>)}</div>}
      {mode === "run" && flow && <section className="mt-5 border-t border-[var(--vui-border-subtle)] pt-4"><h2 className="mb-2 px-2 text-[11px] text-[var(--fg-tertiary)]">运行记录</h2>{props.runs.filter(item => item.flow.id === flow.id).map((item, index) => <VButton key={item.id} variant="ghost" aria-pressed={run?.id === item.id} className="!h-auto !w-full !justify-between !p-2 !text-xs" onClick={() => props.onRun(item.id)}><span>运行 {props.runs.filter(entry => entry.flow.id === flow.id).length - index}</span><span>{statusLabel[item.status]}</span></VButton>)}</section>}
    </div>
    <div className="shrink-0 border-t border-[var(--vui-border-subtle)] px-4 py-4">
      <VNativeButton onClick={props.onMembers} className="mb-3 w-full text-left" aria-label="查看六位示例成员"><span className="mb-2 flex -space-x-1.5">{MEMBERS.map((member,index) => <span key={member.id} className={"flex h-6 w-6 items-center justify-center rounded-full border-2 border-[var(--vui-surface-rail)] text-[9px] " + (index < 3 ? "bg-[var(--vui-status-info-bg)] text-[var(--accent-cool)]" : "bg-[var(--vui-surface-row)] text-[var(--fg-secondary)]")}>{member.initial}</span>)}</span><span className="flex items-center gap-1.5 text-[11px] text-[var(--fg-secondary)]"><span className="h-1.5 w-1.5 rounded-full bg-[var(--state-success)]"/>{MEMBERS.length} 位成员可用</span></VNativeButton>
      <div className="flex items-center justify-between"><span className="flex items-center gap-1 text-[11px] text-[var(--fg-tertiary)]"><Bot size={12}/>模拟团队</span><VIconButton variant="ghost" label="团队设置" icon={<Settings2 size={13}/>} className="!h-7 !min-h-7 !w-7 !border-transparent" onClick={props.onMembers}/></div>
    </div>
  </div>;

  const compactToolbar = <div data-preview-toolbar className="flex h-[52px] shrink-0 items-center justify-between gap-3 border-b border-[var(--vui-border-subtle)] bg-[var(--vui-surface-chat)] px-5 max-sm:h-auto max-sm:min-h-[52px] max-sm:flex-wrap max-sm:gap-2 max-sm:px-3 max-sm:py-2">
    <div className="flex min-w-0 items-center gap-2.5"><h1 className="truncate text-sm font-semibold">{flow?.name || "流程工作台"}</h1>{flow && <span className="hidden shrink-0 items-center gap-1 text-[11px] text-[var(--fg-tertiary)] sm:flex">{props.dirty ? "未保存" : <><Check size={12}/>已保存</>}</span>}</div>
    {flow ? <div className="flex shrink-0 items-center gap-2 max-sm:w-full max-sm:justify-between"><VTabs aria-label="工作模式" value={mode} onValueChange={value => props.onMode(value as "design" | "run")} items={[{ id: "design", label: "设计" }, { id: "run", label: "运行" }]} listClassName="!h-8 !border-0 !bg-[var(--vui-surface-row)] !p-0.5" triggerClassName="!h-7 !min-h-7 !px-3 !py-0 !text-xs"/><span className="flex items-center gap-1"><VButton variant="ghost" className={quiet} icon={<Save size={13}/>} onClick={props.onSave}>保存</VButton>{mode === "run" && active ? <VButton className={quiet} icon={<Square size={12}/>} onClick={props.onStop}>停止</VButton> : <VButton variant="primary" className={primary} icon={<Play size={12}/>} onClick={props.onStart}>{mode === "design" ? "试运行" : "开始运行"}</VButton>}</span></div> : <span className="hidden text-xs text-[var(--fg-tertiary)] md:block">输入 → 团队协作 → 交付结果</span>}
  </div>;

  const empty = <div className="min-h-0 flex-1 overflow-auto bg-[var(--vui-surface-chat)]">
    <section className="mx-auto max-w-[960px] px-8 pb-10 pt-14 max-sm:px-5 max-sm:pt-8">
      <div className="flex items-center gap-3"><span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[var(--vui-status-info-bg)] text-[var(--accent-cool)]"><GitBranch size={21}/></span><h2 className="text-[26px] font-semibold leading-10 max-sm:text-[22px]">从一个流程开始协作</h2></div>
      <p className="mt-2 text-sm leading-7 text-[var(--fg-secondary)]">把输入、成员分工和交付结果串起来，下次任务可以直接复用。</p>
      <div className="mb-3 mt-9 flex items-center justify-between"><h3 className="text-xs font-medium text-[var(--fg-secondary)]">选择一个起点</h3><span className="text-[11px] text-[var(--fg-tertiary)]">模板内容均可编辑</span></div>
      <div className="grid grid-cols-2 gap-4 max-[700px]:grid-cols-1">{EXAMPLE_FLOWS.map((item,index) => <article key={item.id} className="flex min-w-0 flex-col rounded-xl border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-chat)] p-5 transition-colors hover:border-[var(--accent-cool)]/40">
        <div className="mb-4 flex items-center justify-between"><span className="flex h-9 w-9 items-center justify-center rounded-lg bg-[var(--vui-surface-row)] text-[var(--fg-secondary)]">{index ? <FileText size={18}/> : <LayoutTemplate size={18}/>}</span><span className="text-[11px] text-[var(--fg-tertiary)]">{item.steps.length} 个步骤</span></div>
        <h4 className="text-sm font-semibold">{item.name}</h4><p className="mt-2 min-h-10 text-xs leading-6 text-[var(--fg-secondary)]">{item.description}</p>
        <div className="my-5 flex flex-wrap items-center gap-1.5 text-[10px] text-[var(--fg-tertiary)]">{["输入", index ? "分析" : "整理", "核验", "确认", "交付"].map((label,i) => <span key={label} className="flex items-center gap-1.5">{i > 0 && <ArrowRight size={10}/>}<span className="rounded bg-[var(--vui-surface-row)] px-1.5 py-1">{label}</span></span>)}</div>
        <VButton variant={index === 0 ? "primary" : "secondary"} className="!mt-auto !h-8 !min-h-8 !w-full !justify-between !text-xs" trailingIcon={<ArrowRight size={13}/>} onClick={() => props.onTemplate(item.id)}>使用模板</VButton>
      </article>)}</div>
      <div className="mt-4 flex items-center gap-3 rounded-xl border border-dashed border-[var(--vui-border-subtle)] px-5 py-4 max-sm:flex-wrap"><span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-[var(--vui-surface-row)] text-[var(--fg-secondary)]"><Plus size={18}/></span><div className="min-w-0 flex-1"><h3 className="text-xs font-medium">从空白开始</h3><p className="mt-1 text-xs leading-5 text-[var(--fg-tertiary)]">自行定义输入、协作步骤与交付方式。</p></div><VButton className="!h-8 !min-h-8 !text-xs" onClick={props.onCreate}>创建流程</VButton></div>
      <p className="mt-6 flex items-start gap-2 text-xs leading-6 text-[var(--fg-tertiary)]"><Users size={14} className="mt-1 shrink-0"/>团队成员已就绪，创建后可为每个步骤分配负责人。</p>
    </section>
  </div>;

  const canvas = <div className="flex h-full min-h-0 flex-col">{compactToolbar}{currentFlow ? <>
    <div className="flex h-11 shrink-0 items-center justify-between gap-2 px-5 max-sm:px-3"><span className="flex items-center gap-2 text-[11px] text-[var(--fg-secondary)]"><GitBranch size={13}/>{mode === "design" ? "流程编排" : "执行过程"}<span className="text-[var(--fg-tertiary)]">· {currentFlow.steps.length} 个步骤</span></span>{mode === "design" ? <VButton variant="ghost" className="!h-7 !min-h-7 !border-transparent !text-xs" icon={<Plus size={13}/>} onClick={props.onAddStep}>添加步骤</VButton> : <span className="text-xs text-[var(--fg-secondary)]">{run ? statusLabel[run.status] : "尚未开始"}</span>}</div>
    <div className="min-h-0 flex-1"><FlowEditor flow={currentFlow} selectedId={props.selectedId || currentFlow.steps[0]?.id || ""} mode={mode} run={run} onSelect={selectStep} onAdd={props.onAddStep}/></div>
    {mode === "run" && run && <div className="h-[180px] shrink-0 overflow-auto border-t border-[var(--vui-border-subtle)] px-5 py-3"><VTabs aria-label="运行内容" value={bottomTab} onValueChange={setBottomTab} items={[{ id: "messages", label: "协作记录" }, { id: "artifacts", label: "产物" }]} listClassName="!border-0 !bg-transparent !p-0" triggerClassName="!px-2.5"/>{bottomTab === "messages" ? <div className="mt-3 grid gap-2" aria-live="polite">{run.messages.map((message,index) => <p key={index} className="flex gap-3 text-xs text-[var(--fg-secondary)]"><span className="text-[var(--fg-tertiary)]">{String(index+1).padStart(2,"0")}</span>{message}</p>)}</div> : <VButton variant="ghost" onClick={props.onArtifact} className="mt-2 !text-xs" icon={<FileText size={15}/>}>查看示例产物</VButton>}</div>}
  </> : empty}</div>;

  return <div className="flex h-dvh min-w-0 flex-col overflow-hidden bg-[var(--vui-surface-chat)] text-[var(--fg-primary)]">
    <header data-preview-topbar className="flex h-10 shrink-0 items-center justify-between gap-3 border-b border-[var(--vui-border-subtle)] bg-[var(--vui-surface-rail)] px-3">
      <nav aria-label="主导航示意" className="flex min-w-0 items-center gap-1"><span className="mr-2 flex h-6 w-6 items-center justify-center text-[var(--fg-tertiary)]"><ArrowLeft size={15}/></span>{["对话","智能体","团队","进化","记忆库","Agent 管理"].map(label => <span key={label} className={"rounded-md px-2.5 py-1 text-xs " + (label === "团队" ? "bg-[var(--vui-surface-row)] font-medium text-[var(--fg-primary)]" : "hidden text-[var(--fg-secondary)] md:block")}>{label}</span>)}</nav>
      <div className="flex shrink-0 items-center gap-3"><span className="hidden items-center gap-1.5 text-[10px] text-[var(--fg-tertiary)] min-[1100px]:flex"><span className="h-1.5 w-1.5 rounded-full bg-[var(--state-success)]"/>本地预览 · 模拟数据</span><VTabs aria-label="预览页面" value={flow ? "design" : "empty"} onValueChange={props.onScene} items={[{id:"empty",label:"空白页"},{id:"design",label:"编辑页"}]} listClassName="!h-7 !border-[var(--vui-border-subtle)] !bg-[var(--vui-surface-chat)] !p-0.5" triggerClassName="!h-6 !min-h-6 !px-3 !py-0 !text-[11px]"/></div>
    </header>
    {props.notice && <div role="status" className="flex shrink-0 items-center justify-between gap-2 bg-[var(--vui-status-info-bg)] px-5 py-1 text-xs text-[var(--accent-cool)]"><span>{props.notice}</span><VButton variant="ghost" className="!h-7 !min-h-7 !border-transparent !text-xs" onClick={props.onDismiss}>关闭提示</VButton></div>}
    <main className="min-h-0 min-w-0 flex-1"><VCanvasWorkbenchPage hideHeader chrome="embedded" title="团队流程工作台预览" ariaLabel="团队流程工作台预览" domainRecipe="generic-team-workspace-preview" className="!h-full !min-h-0 !w-full !border-0 !p-0" layoutId={WORKBENCH_LAYOUT_IDS.teams} resize={{ sidebar:{id:"flows",defaultWidth:224,minWidth:200,maxWidth:280},aside:{id:"flow-inspector",defaultWidth:312,minWidth:280,maxWidth:400} }} rail={rail} railClassName="!overflow-hidden !rounded-none !border-0" canvas={canvas} canvasClassName="!rounded-none !border-0 !bg-[var(--vui-surface-chat)]" inspector={props.inspector} inspectorClassName="!rounded-none !border-0 !border-l !border-[var(--vui-border-subtle)] !bg-[var(--vui-surface-chat)]" responsive={{enabled:true,rail:{label:"流程与成员",open:railOpen,onOpenChange:setRailOpen},inspector:{label:mode === "design" ? "节点配置" : "运行详情",open:props.inspectorOpen,onOpenChange:props.onInspectorOpen}}}/></main>
  </div>;
}
