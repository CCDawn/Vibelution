import styles from "./WorkbenchShell.styles";
import { useState, type ReactNode } from "react";
import { Check, FileText, GitBranch, Plus, Play, Save, Settings2, Square, Users } from "lucide-react";
import { VButton, VCanvasWorkbenchPage, VIconButton, VNativeButton, VSelect, VTabs } from "../../../components/vui";
import { WORKBENCH_LAYOUT_IDS } from "../../../components/layout/workbenchLayoutIds";
import { FlowEditor } from "./FlowEditor";
import { WorkflowStart } from "./WorkflowStart";
import type { Flow, Run, WorkflowMember } from "./workflowModel";
type Props = {
    flows: Flow[];
    flow?: Flow;
    run?: Run;
    runs: Run[];
    mode: "design" | "run";
    teamId: string;
    teams: {
        id: string;
        label: string;
    }[];
    members: WorkflowMember[];
    onTeam: (id: string) => void;
    onDiscussion: () => void;
    onHistory: () => void;
    saving: boolean;
    pending: boolean;
    loading: boolean;
    error: string;
    onReload: () => void;
    selectedId: string;
    dirty: boolean;
    inspector: ReactNode;
    notice: string;
    inspectorOpen: boolean;
    onInspectorOpen: (open: boolean) => void;
    onMode: (mode: "design" | "run") => void;
    onFlow: (id: string) => void;
    onStep: (id: string) => void;
    onRun: (id: string) => void;
    onSave: () => void;
    onStart: () => void;
    onStop: () => void;
    onCreate: () => void;
    onTemplate: (id: string) => void;
    onAddStep: () => void;
    onMembers: () => void;
    onArtifact: () => void;
    onDismiss: () => void;
};
const primary = "!h-8 !min-h-8 !rounded-md !px-3 !text-vui-micro-13";
const quiet = "!h-8 !min-h-8 !border-transparent !text-[var(--fg-secondary)] !text-vui-micro-13";
const statusLabel = { running: "正在执行", waiting: "需要你确认", completed: "已完成", failed: "执行失败", stopped: "已停止" };

export function WorkbenchShell(props: Props) {
  const [leftTab, setLeftTab] = useState("flows");
  const [bottomTab, setBottomTab] = useState("messages");
  const [railOpen, setRailOpen] = useState(false);
  const { flow, run, mode } = props;
  const active = run?.status === "running" || run?.status === "waiting";
  const currentFlow = mode === "run" && run ? run.flow : flow;
  const selectStep = (id: string) => { props.onStep(id); props.onInspectorOpen(true); };
  const visibleFlows = props.flows;

  const rail = <div className={styles.part1}>
    <div className={styles.part2}>
      <span className={styles.part3}><Users size={15}/></span>
      <VSelect aria-label="切换团队" selectedKey={props.teamId} options={props.teams} onSelectionChange={key => props.onTeam(String(key))} className={styles.part4}/>
    </div>
    <div className={styles.part5}><VTabs aria-label="工作区导航" value={leftTab} onValueChange={setLeftTab} items={[{ id: "flows", label: "流程" }, { id: "members", label: "成员" }]} listClassName="!h-8 !w-full !border-0 !bg-[var(--vui-surface-row)] !p-0.5" triggerClassName="!h-7 !min-h-7 !flex-1 !py-0 !text-vui-2xs data-[state=active]:!text-[var(--fg-primary)]"/></div>
    <div className={styles.part6}>
      {leftTab === "flows" ? <>
        <div className={styles.part7}><span className={styles.part8}>我的流程 <span className={styles.part9}>{visibleFlows.length}</span></span><VIconButton label="新建流程" icon={<Plus size={14}/>} variant="ghost" className={styles.part10} onClick={() => { setRailOpen(false); props.onCreate(); }}/></div>
        {visibleFlows.length ? <div className={styles.part11}>{visibleFlows.map(item => <VNativeButton key={item.id} aria-pressed={flow?.id === item.id} onClick={() => { props.onFlow(item.id); setRailOpen(false); }} className={"flex w-full items-start gap-2.5 rounded-lg border px-3 py-3 text-left transition-colors " + (flow?.id === item.id ? "border-[var(--vui-status-info-bg)] bg-[var(--vui-status-info-bg)] text-[var(--accent-cool)]" : "border-transparent hover:bg-[var(--vui-surface-row-hover)]")}>
          <GitBranch size={15} className={styles.part12}/><span className={styles.part13}><span className={styles.part14}>{item.name}</span><span className={styles.part15}>{item.steps.length} 个步骤 · {item.fields.length} 个输入</span></span>
        </VNativeButton>)}</div> : <p className={styles.part16}>还没有流程<br/>从右侧选择模板开始。</p>}
      </> : <div className={styles.part17}>{props.members.map(member => <VNativeButton key={member.id} className={styles.part18} onClick={props.onMembers}><span className={styles.part19}>{member.initial}</span><span className={styles.part13}><span className={styles.part20}>{member.name}</span><span className={styles.part21}>{member.detail}</span></span></VNativeButton>)}</div>}
      {mode === "run" && flow && <section className={styles.part22}><h2 className={styles.part23}>运行记录</h2>{props.runs.filter(item => item.flow.id === flow.id).map((item, index) => <VButton key={item.id} variant="ghost" aria-pressed={run?.id === item.id} className={styles.part24} onClick={() => props.onRun(item.id)}><span>运行 {props.runs.filter(entry => entry.flow.id === flow.id).length - index}</span><span>{statusLabel[item.status]}</span></VButton>)}</section>}
    </div>
    <div className={styles.part25}>
      <VNativeButton onClick={props.onMembers} className={styles.part26} aria-label="查看团队成员"><span className={styles.part27}>{props.members.slice(0,6).map((member,index) => <span key={member.id} className={"flex h-6 w-6 items-center justify-center rounded-full border-2 border-[var(--vui-surface-rail)] text-vui-micro-9 " + (index < 3 ? "bg-[var(--vui-status-info-bg)] text-[var(--accent-cool)]" : "bg-[var(--vui-surface-row)] text-[var(--fg-secondary)]")}>{member.initial}</span>)}</span><span className={styles.part28}><span className={styles.part29}/>{props.members.filter(member => member.available).length} 位成员可用</span></VNativeButton>
      <div className={styles.part30}><span className={styles.part31}><VButton variant="ghost" className={styles.part32} onClick={props.onDiscussion}>团队讨论</VButton><VButton variant="ghost" className={styles.part32} onClick={props.onHistory}>已有记录</VButton></span><VIconButton variant="ghost" label="团队设置" icon={<Settings2 size={13}/>} className={styles.part10} onClick={props.onMembers}/></div>
    </div>
  </div>;

  const compactToolbar = <div data-team-workspace-toolbar className={styles.part33}>
    <div className={styles.part34}><h1 className={styles.part35}>{flow?.name || "流程工作台"}</h1>{flow && <span className={styles.part36}>{props.dirty ? "未保存" : <><Check size={12}/>已保存</>}</span>}</div>
    {currentFlow ? <div className={styles.part37}><VTabs aria-label="工作模式" value={mode} onValueChange={value => props.onMode(value as "design" | "run")} items={[{ id: "design", label: "设计" }, { id: "run", label: "运行" }]} listClassName="!h-8 !border-0 !bg-[var(--vui-surface-row)] !p-0.5" triggerClassName="!h-7 !min-h-7 !px-3 !py-0 !text-vui-2xs"/><span className={styles.part31}><VButton variant="ghost" className={quiet} icon={<Save size={13}/>} isPending={props.saving} isDisabled={props.loading || props.saving || props.pending} onClick={props.onSave}>保存</VButton>{mode === "run" && active ? <VButton className={quiet} icon={<Square size={12}/>} isPending={props.pending || Boolean(run?.stopRequested)} isDisabled={props.pending || Boolean(run?.stopRequested)} onClick={props.onStop}>{run?.stopRequested ? "正在停止" : "停止"}</VButton> : <VButton variant="primary" className={primary} icon={<Play size={12}/>} isPending={props.pending} isDisabled={props.loading || props.saving || props.pending} onClick={props.onStart}>{mode === "design" ? "试运行" : "开始运行"}</VButton>}</span></div> : <span className={styles.part38}>输入 → 团队协作 → 交付结果</span>}
  </div>;

  const canvas = <div className={styles.part39}>{compactToolbar}{props.loading ? <div role="status" className={styles.part40}>正在读取流程…</div> : props.error ? <div className={styles.part41}>流程暂未读取成功，请重新读取。</div> : currentFlow ? <>
    <div className={styles.part42}><span className={styles.part43}><GitBranch size={13}/>{mode === "design" ? "流程编排" : "执行过程"}<span className={styles.part44}>· {currentFlow.steps.length} 个步骤</span></span>{mode === "design" ? <VButton variant="ghost" className={styles.part45} icon={<Plus size={13}/>} onClick={props.onAddStep}>添加步骤</VButton> : <span className={styles.part46}>{run ? run.stopRequested && run.status === "running" ? "正在停止" : statusLabel[run.status] : "尚未开始"}</span>}</div>
    <div className={styles.part47}><FlowEditor flow={currentFlow} selectedId={props.selectedId || currentFlow.steps[0]?.id || ""} mode={mode} run={run} members={props.members} onSelect={selectStep} onAdd={props.onAddStep}/></div>
    {mode === "run" && run && <div className={styles.part48}><VTabs aria-label="运行内容" value={bottomTab} onValueChange={setBottomTab} items={[{ id: "messages", label: "协作记录" }, { id: "artifacts", label: "产物" }]} listClassName="!border-0 !bg-transparent !p-0" triggerClassName="!px-2.5"/>{bottomTab === "messages" ? <div className={styles.part49} aria-live="polite">{run.messages.map((message,index) => <p key={index} className={styles.part50}><span className={styles.part44}>{String(index+1).padStart(2,"0")}</span>{message}</p>)}</div> : run.status === "completed" || run.status === "waiting" || run.attempts?.some(attempt => attempt.status === "completed") ? <VButton variant="ghost" onClick={props.onArtifact} className={styles.part51} icon={<FileText size={15}/>}>查看产物</VButton> : <p className={styles.part52}>完成相关步骤后，产物会显示在这里。</p>}</div>}
  </> : <WorkflowStart onTemplate={props.onTemplate} onCreate={props.onCreate}/> }</div>;

  return <div className={styles.part53}>
    {props.notice && <div role="status" className={styles.part54}><span>{props.notice}</span><VButton variant="ghost" className={styles.part45} onClick={props.onDismiss}>关闭提示</VButton></div>}
    {props.error && <div role="alert" className={styles.part55}><span>{props.error}</span><VButton variant="ghost" onClick={props.onReload}>重新读取</VButton></div>}
    <main className={styles.part56}><VCanvasWorkbenchPage hideHeader chrome="embedded" title="团队流程工作台" ariaLabel="团队流程工作台" domainRecipe="generic-team-workspace" className={styles.part57} layoutId={WORKBENCH_LAYOUT_IDS.teams} resize={{ sidebar:{id:"flows",defaultWidth:224,minWidth:200,maxWidth:280},aside:{id:"flow-inspector",defaultWidth:312,minWidth:280,maxWidth:400} }} rail={rail} railClassName="!overflow-hidden !rounded-none !border-0" canvas={canvas} canvasClassName="!rounded-none !border-0 !bg-[var(--vui-surface-chat)]" inspector={props.inspector} inspectorClassName="!rounded-none !border-0 !border-l !border-[var(--vui-border-subtle)] !bg-[var(--vui-surface-chat)]" responsive={{enabled:true,rail:{label:"流程与成员",open:railOpen,onOpenChange:setRailOpen},inspector:{label:mode === "design" ? "节点配置" : "运行详情",open:props.inspectorOpen,onOpenChange:props.onInspectorOpen}}}/></main>
  </div>;
}
