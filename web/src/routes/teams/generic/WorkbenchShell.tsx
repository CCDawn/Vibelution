import styles from "./WorkbenchShell.styles";
import { useState, type ReactNode } from "react";
import { ArrowRight, Check, FileText, GitBranch, Plus, Play, Save, Settings2, Square, Users } from "lucide-react";
import { VButton, VCanvasWorkbenchPage, VSelect, VTabs } from "../../../components/vui";
import { WORKBENCH_LAYOUT_IDS } from "../../../components/layout/workbenchLayoutIds";
import { FlowEditor } from "./FlowEditor";
import { type Flow, type Run, type WorkflowMember } from "./workflowModel";
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
    onAddStep: () => void;
    onMembers: () => void;
    onArtifact: () => void;
    onDismiss: () => void;
};
const primaryButton = styles.surface1;
const statusLabel = { running: "正在执行", waiting: "需要你确认", completed: "已完成", failed: "执行失败", stopped: "已停止" };
export function WorkbenchShell(props: Props) {
    const [leftTab, setLeftTab] = useState("flows");
    const [bottomTab, setBottomTab] = useState("messages");
    const [railOpen, setRailOpen] = useState(false);
    const { flow, run, mode } = props;
    const active = run?.status === "running" || run?.status === "waiting";
    const currentFlow = mode === "run" && run ? run.flow : flow;
    const selectStep = (id: string) => { props.onStep(id); props.onInspectorOpen(true); };
    const rail = <div className={styles.column1}>
    <div className={styles.control1}><VSelect aria-label="切换团队" selectedKey={props.teamId} options={props.teams} onSelectionChange={key => props.onTeam(String(key))} className={styles.heading1}/><p className={styles.caption1}>{props.members.length} 位成员 · 自定义协作</p></div>
    <div className={styles.control2}><VTabs aria-label="工作区导航" value={leftTab} onValueChange={setLeftTab} items={[{ id: "flows", label: "流程" }, { id: "members", label: "成员" }]} listClassName={styles.surface2} triggerClassName={styles.row1}/></div>
    <div className={styles.row2}>
      {leftTab === "flows" ? <div className={styles.grid1}>{props.flows.map(item => <VButton key={item.id} variant="ghost" contentLayout="plain" aria-pressed={flow?.id === item.id} onClick={() => { props.onFlow(item.id); setRailOpen(false); }} className={[styles.text1, flow?.id === item.id ? styles.surface3 : styles.surface4].filter(Boolean).join(" ")}><span className={styles.row3}><GitBranch size={16} className={[styles.control3, flow?.id === item.id ? styles.text2 : styles.text3].filter(Boolean).join(" ")}/><span className={styles.control4}><span className={styles.text4}>{item.name}</span><span className={styles.caption2}>{item.steps.length} 个步骤 · {item.fields.length} 个输入</span></span></span></VButton>)}</div> : <div className={styles.grid2}>{props.members.map(member => <VButton key={member.id} variant="ghost" className={styles.text5} onClick={() => { setRailOpen(false); props.onMembers(); }}><span className={styles.row4}><span className={styles.grid3}>{member.initial}</span><span><span className={styles.text6}>{member.name}</span><span className={styles.caption3}>{member.detail}</span></span></span></VButton>)}</div>}
      {mode === "run" && flow && <section className={styles.control5}><h2 className={styles.caption4}>运行记录</h2>{props.runs.filter(item => item.flow.id === flow.id).length ? props.runs.filter(item => item.flow.id === flow.id).map((item, index) => <VButton key={item.id} variant="ghost" aria-pressed={run?.id === item.id} className={[styles.caption5, run?.id === item.id ? styles.surface5 : ""].filter(Boolean).join(" ")} onClick={() => props.onRun(item.id)}><span>运行 {props.runs.filter(entry => entry.flow.id === flow.id).length - index}</span><span className={styles.text7}>{statusLabel[item.status]}</span></VButton>) : <p className={styles.caption6}>暂无运行记录</p>}</section>}
    </div>
    <div className={styles.grid4}><VButton density="normal" className={styles.surface6} icon={<Plus size={15}/>} onClick={() => { setRailOpen(false); props.onCreate(); }}>新建流程</VButton><div className={styles.row5}><VButton variant="ghost" className={styles.caption7} onClick={props.onDiscussion}>团队讨论</VButton><VButton variant="ghost" className={styles.caption7} onClick={props.onHistory}>已有记录</VButton></div><div className={styles.caption8}><span className={styles.row6}><span className={styles.surface7}/>{props.members.filter(member => member.available).length} 位成员可用</span><VButton variant="ghost" aria-label="团队设置" isIconOnly onClick={() => { setRailOpen(false); props.onMembers(); }}><Settings2 size={14}/></VButton></div></div>
  </div>;
    const toolbar = <div className={styles.row7}>
    <div className={styles.row8}><div className={styles.row9}><h1 className={styles.heading2}>{flow?.name || "我的工作台"}</h1>{props.dirty ? <span className={styles.surface8}>草稿</span> : <span className={styles.caption9}><Check size={12}/>已保存</span>}</div><p className={styles.caption10}>{flow?.description || "配置输入、步骤与团队分工"}</p></div>
    <div className={styles.row10}><VTabs aria-label="工作模式" value={mode} onValueChange={value => props.onMode(value as "design" | "run")} items={[{ id: "design", label: "设计" }, { id: "run", label: "运行" }]} listClassName={styles.surface9} triggerClassName={styles.text8}/><VButton density="normal" variant="ghost" aria-label="保存流程" className={styles.text9} isPending={props.saving} isDisabled={!flow || props.saving || props.pending} icon={<Save size={15}/>} onClick={props.onSave}>保存</VButton>{mode === "run" && active ? <VButton density="normal" className={styles.control6} isPending={props.pending || (run?.stopRequested && run.status === "running")} isDisabled={props.pending || (run?.stopRequested && run.status === "running")} icon={<Square size={13}/>} onClick={props.onStop}>{(run?.stopRequested && run.status === "running") ? "正在停止" : "停止"}</VButton> : <VButton density="normal" variant="primary" className={primaryButton} isPending={props.pending} isDisabled={!flow || props.saving || props.pending} icon={<Play size={14}/>} onClick={props.onStart}>{mode === "design" ? "试运行" : "开始运行"}</VButton>}</div>
  </div>;
    const canvas = props.loading ? <div role="status" className={styles.grid5}>正在读取流程…</div> : currentFlow ? <div className={styles.column2}>
    <div className={styles.row11}><span className={styles.caption11}><GitBranch size={15}/>{mode === "design" ? "流程编排" : "执行过程"}<span className={styles.text10}>· {currentFlow.steps.length} 个步骤</span></span>{mode === "design" ? <VButton variant="ghost" className={styles.caption12} icon={<Plus size={14}/>} onClick={props.onAddStep}>添加步骤</VButton> : <span className={[styles.caption13, run?.status === "waiting" ? styles.surface10 : styles.surface11].filter(Boolean).join(" ")}>{run ? run.stopRequested && run.status === "running" ? "正在停止" : statusLabel[run.status] : "尚未开始"}</span>}</div>
    <div className={styles.row12}><FlowEditor flow={currentFlow} selectedId={props.selectedId || currentFlow.steps[0]?.id || ""} mode={mode} run={run} members={props.members} onSelect={selectStep} onAdd={props.onAddStep}/></div>
    {mode === "run" && run && <div className={styles.surface12}><VTabs aria-label="运行内容" value={bottomTab} onValueChange={setBottomTab} items={[{ id: "messages", label: "协作记录" }, { id: "artifacts", label: "产物" }]} listClassName={styles.surface13} triggerClassName={styles.control7}/>{bottomTab === "messages" ? <div className={styles.grid6} aria-live="polite">{run.messages.map((message, index) => <p key={index} className={styles.caption14}><span className={styles.text11}>{String(index + 1).padStart(2, "0")}</span>{message}</p>)}</div> : run.status === "completed" || run.status === "waiting" || run.attempts?.some(attempt => attempt.status === "completed") ? <VButton variant="ghost" onClick={props.onArtifact} className={styles.surface14}><span className={styles.row13}><FileText size={22} className={styles.text2}/><span><span className={styles.text6}>{run.flow.name} · {run.status === "completed" ? "交付文档" : run.status === "waiting" ? "待确认初稿" : "已有产物"}</span><span className={styles.caption15}>查看内容与本次任务输入</span></span><ArrowRight size={15} className={styles.text12}/></span></VButton> : <p className={styles.caption16}>完成相关步骤后，产物会显示在这里。</p>}</div>}
  </div> : <div className={styles.grid7}><div className={styles.text13}><h2 className={styles.heading3}>创建你的第一个流程</h2><p className={styles.text14}>从空白开始，或使用可编辑模板。</p><VButton variant="primary" className={[primaryButton, styles.control8].filter(Boolean).join(" ")} onClick={() => { setRailOpen(false); props.onCreate(); }}>创建流程</VButton></div></div>;
    return <div className={styles.column3}>
    {props.notice && <div role="status" className={styles.caption17}><span>{props.notice}</span><VButton variant="ghost" onClick={props.onDismiss}>关闭提示</VButton></div>}
    {props.error && <div role="alert" className={styles.row14}><span>{props.error}</span><VButton variant="ghost" onClick={props.onReload}>重新读取</VButton></div>}
    <main className={styles.row15}><VCanvasWorkbenchPage hideHeader title="通用团队工作台" ariaLabel="通用团队工作台" domainRecipe="generic-team-workspace" className={styles.control9} toolbar={toolbar} toolbarClassName={styles.surface15} layoutId={WORKBENCH_LAYOUT_IDS.teams} resize={{ sidebar: { id: "flows", defaultWidth: 216, minWidth: 190, maxWidth: 270 }, aside: { id: "flow-inspector", defaultWidth: 320, minWidth: 290, maxWidth: 430 } }} rail={rail} railClassName={styles.surface16} canvas={canvas} canvasClassName={styles.surface17} inspector={props.inspector} inspectorClassName={styles.surface17} responsive={{ enabled: true, rail: { label: "流程与成员", open: railOpen, onOpenChange: setRailOpen }, inspector: { label: mode === "design" ? "节点配置" : "运行详情", open: props.inspectorOpen, onOpenChange: props.onInspectorOpen } }}/></main>
  </div>;
}
