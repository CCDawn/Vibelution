import styles from "./GenericWorkflowWorkspace.styles";
import { useState, type ReactNode } from "react";
import { ArrowDown, ArrowUp, Check, FileText, Play, Plus, Save, Trash2 } from "lucide-react";
import { VButton, VCheckbox, VConfirmDialog, VDialog, VInput, VRouteLinkButton, VSelect, VTextarea } from "../../../components/vui";
import type { Team } from "../../../api/types";
import { WorkbenchShell } from "./WorkbenchShell";
import { WorkflowArtifactDialog } from "./WorkflowArtifactDialog";
import { useWorkflowWorkspace } from "./useWorkflowWorkspace";
import { createWorkflow, workflowTemplateOptions } from "./workflowTemplates";
import { copyFlow, KIND_LABEL, memberName, missingInputLabels, workflowMembers, type Flow, type InputField, type Step } from "./workflowModel";
import "./workspace.css";
const primary = styles.surface1;
const field = styles.text1;
const muted = styles.text2;
const statusLabel = { running: "运行中", waiting: "等待确认", completed: "已完成", failed: "执行失败", stopped: "已停止" } as const;
function SectionTitle({ children, extra }: {
    children: ReactNode;
    extra?: ReactNode;
}) {
    return <div className={styles.row1}><h3 className={styles.heading1}>{children}</h3>{extra}</div>;
}
function Field({ label, children }: {
    label: string;
    children: ReactNode;
}) {
    return <div className={styles.grid1}><div className={styles.caption1}>{label}</div>{children}</div>;
}
type Props = {
    team: Team;
    teams: {
        id: string;
        label: string;
    }[];
    onTeam: (id: string) => void;
    onDiscussion: () => void;
    onHistory: () => void;
};
export function GenericWorkflowWorkspace({ team, teams, onTeam, onDiscussion, onHistory }: Props) {
    const workspace = useWorkflowWorkspace(team.teamId);
    const { flows, flow, runs, run, dirty, editFlow } = workspace;
    const flowId = flow?.id || "";
    const members = workflowMembers(team);
    const MEMBERS = members;
    const ownerName = (id: string) => memberName(id, members);
    const [mode, setMode] = useState<"design" | "run">("design");
    const [selectedId, setSelectedId] = useState("");
    const [launchFlow, setLaunchFlow] = useState<Flow | null>(null);
    const [launchKey, setLaunchKey] = useState("");
    const [values, setValues] = useState<Record<string, string>>({});
    const [optionDrafts, setOptionDrafts] = useState<Record<string, string>>({});
    const [formError, setFormError] = useState("");
    const [notice, setNotice] = useState("");
    const [showCreate, setShowCreate] = useState(false);
    const [newName, setNewName] = useState("");
    const [createTemplate, setCreateTemplate] = useState("blank");
    const [showAddStep, setShowAddStep] = useState(false);
    const [stepName, setStepName] = useState("");
    const [stepKind, setStepKind] = useState<"agent" | "human">("agent");
    const [showMembers, setShowMembers] = useState(false);
    const [showArtifact, setShowArtifact] = useState(false);
    const [deleteStepId, setDeleteStepId] = useState("");
    const [inspectorOpen, setInspectorOpen] = useState(false);
    const displayedFlow = mode === "run" && run ? run.flow : flow;
    const step = displayedFlow?.steps.find(item => item.id === selectedId) ?? displayedFlow?.steps[0];
    const active = run?.status === "running" || run?.status === "waiting";
    const currentAttempt = run?.attempts?.filter(item => item.nodeId === run.flow.steps[run.current]?.id).at(-1);
    const currentSessionUrl = currentAttempt?.sessionId ? `/chat?${new URLSearchParams({ session: currentAttempt.sessionId, turn: currentAttempt.turnId })}` : "";
    function selectFlow(id: string) { workspace.selectFlow(id); setSelectedId(""); setNotice(""); setInspectorOpen(false); }
    function editStep(patch: Partial<Step>) { editFlow(current => ({ ...current, steps: current.steps.map(item => item.id === (selectedId || current.steps[0]?.id) ? { ...item, ...patch } : item) })); }
    function editField(id: string, patch: Partial<InputField>) { editFlow(current => ({ ...current, fields: current.fields.map(item => item.id === id ? { ...item, ...patch } : item) })); }
    async function save() { const saved = await workspace.save(); if (saved)
        setNotice("流程已保存。"); }
    async function openRun() {
        const saved = await workspace.save();
        if (!saved)
            return;
        setLaunchFlow(copyFlow(saved));
        setLaunchKey(crypto.randomUUID());
        setValues({});
        setFormError("");
    }
    function updateValue(id: string, value: string) { setValues(current => ({ ...current, [id]: value })); setLaunchKey(crypto.randomUUID()); }
    async function startRun() {
        if (!launchFlow)
            return;
        const missing = missingInputLabels(launchFlow, values);
        if (missing.length) {
            setFormError(`请填写：${missing.join("、")}`);
            return;
        }
        const started = await workspace.start(launchFlow, values, launchKey);
        if (started) {
            setMode("run");
            setLaunchFlow(null);
            setSelectedId(started.flow.steps[started.current]?.id || "input");
            setInspectorOpen(false);
        }
    }
    async function confirmRun() {
        const continued = await workspace.command("confirm");
        if (continued)
            setSelectedId(continued.flow.steps[continued.current]?.id || "deliver");
    }
    function addField() {
        editFlow(current => ({ ...current, fields: [...current.fields, { id: `field-${crypto.randomUUID()}`, label: "新输入项", kind: "text", required: false, options: [] }] }));
    }
    function createFlow() {
        if (!newName.trim())
            return;
        workspace.addFlow(createWorkflow(newName, createTemplate, members));
        setMode("design");
        setSelectedId("");
        setInspectorOpen(false);
        setShowCreate(false);
    }
    function addStep() {
        if (!stepName.trim())
            return;
        const id = `step-${crypto.randomUUID()}`;
        editFlow(current => { const steps = [...current.steps]; steps.splice(Math.max(1, steps.length - 1), 0, { id, label: stepName.trim(), kind: stepKind, owner: stepKind === "human" ? "用户" : members.find(member => member.available)?.id || "", instruction: "" }); return { ...current, steps }; });
        setSelectedId(id);
        setShowAddStep(false);
        setInspectorOpen(true);
    }
    function moveStep(direction: -1 | 1) {
        editFlow(current => { const steps = [...current.steps]; const index = steps.findIndex(item => item.id === selectedId); const target = index + direction; if (index < 1 || target < 1 || target >= steps.length - 1)
            return current; [steps[index], steps[target]] = [steps[target], steps[index]]; return { ...current, steps }; });
    }
    const inspector = displayedFlow && <div className={styles.column1}>
    <div className={styles.control1}><div className={[styles.caption2, muted].filter(Boolean).join(" ")}>{mode === "design" ? "节点配置" : "运行详情"}</div><h2 className={styles.heading2}>{mode === "design" ? step?.label ?? "流程配置" : run ? run.stopRequested && run.status === "running" ? "正在停止" : statusLabel[run.status] : "准备运行"}</h2></div>
    <div className={styles.grid2}>
      {mode === "design" && step ? <>
        <Field label="步骤名称"><VInput aria-label="步骤名称" value={step.label} onChange={event => editStep({ label: event.target.value })} className={field}/></Field>
        <div className={styles.caption3}><span className={[styles.surface2, muted].filter(Boolean).join(" ")}>{KIND_LABEL[step.kind]}</span></div>
        {step.kind === "input" ? <>
          <SectionTitle extra={<VButton variant="ghost" onClick={addField} icon={<Plus size={14}/>}>添加输入</VButton>}>运行时收集</SectionTitle>
          {displayedFlow.fields.length === 0 && <p className={[styles.caption4, muted].filter(Boolean).join(" ")}>可以直接运行，也可以添加这条流程需要的信息。</p>}
          {displayedFlow.fields.map((item, index) => <div key={item.id} className={styles.grid3}>
            <div className={styles.row2}><span className={[styles.caption5, muted].filter(Boolean).join(" ")}>输入 {index + 1}</span><VButton variant="ghost" isIconOnly aria-label={`删除输入${index + 1}`} onClick={() => editFlow(current => ({ ...current, fields: current.fields.filter(field => field.id !== item.id) }))}><Trash2 size={13}/></VButton></div>
            <VInput aria-label={`输入${index + 1}名称`} value={item.label} onChange={event => editField(item.id, { label: event.target.value })} className={field}/>
            <VSelect aria-label={`输入${index + 1}类型`} selectedKey={item.kind} options={[{ id: "text", label: "单行文本" }, { id: "paragraph", label: "多行文本" }, { id: "select", label: "下拉选择" }]} onSelectionChange={key => { setOptionDrafts(current => { const next = { ...current }; delete next[`${flowId}:${item.id}`]; return next; }); editField(item.id, { kind: key as InputField["kind"], options: key === "select" ? item.options.length ? item.options : ["选项一", "选项二"] : [] }); }}/>
            {item.kind === "select" && <VInput aria-label={`输入${index + 1}选项`} placeholder="选项，以中文逗号分隔" value={optionDrafts[`${flowId}:${item.id}`] ?? item.options.join("，")} onChange={event => { const text = event.target.value; setOptionDrafts(current => ({ ...current, [`${flowId}:${item.id}`]: text })); editField(item.id, { options: text.split(/[，,]/).map(value => value.trim()).filter(Boolean) }); }} className={field}/>}
            <VCheckbox isSelected={item.required} onChange={required => editField(item.id, { required })}>必填</VCheckbox>
          </div>)}
        </> : <>
          {step.kind !== "human" && <Field label="负责成员"><VSelect aria-label="负责成员" selectedKey={step.owner || "__collect__"} onSelectionChange={key => editStep({ owner: key === "__collect__" ? "" : String(key) })} options={[...(step.kind === "output" ? [{ id: "__collect__", label: "直接交付已有结果" }] : []), ...MEMBERS.map(item => ({ id: item.id, label: item.available ? item.name : `${item.name}（不可用）`, disabled: !item.available }))]}/></Field>}
          <Field label={step.kind === "human" ? "确认说明" : "执行要求"}><VTextarea aria-label="步骤要求" value={step.instruction} rows={5} onChange={event => editStep({ instruction: event.target.value })} className={styles.text3}/></Field>
          <p className={[styles.caption4, muted].filter(Boolean).join(" ")}>{step.kind === "human" ? "流程到达这里时暂停，等待用户确认后继续。" : "此步骤使用本次运行的输入，以及前序步骤的结果。"}</p>
        </>}
      </> : mode === "run" && run ? <>
        <div><SectionTitle>本次任务</SectionTitle><dl className={styles.grid4}>{run.flow.fields.map(item => <div key={item.id}><dt className={[styles.caption5, muted].filter(Boolean).join(" ")}>{item.label}</dt><dd className={styles.text4}>{run.values[item.id] || "未填写"}</dd></div>)}</dl></div>
        {step && <div className={styles.control2}><SectionTitle>所选步骤</SectionTitle><p className={styles.text5}>{step.label}</p><p className={[styles.caption6, muted].filter(Boolean).join(" ")}>{KIND_LABEL[step.kind]} · {ownerName(step.owner)}</p><p className={[styles.caption7, muted].filter(Boolean).join(" ")}>{step.instruction || "此步骤没有额外执行要求。"}</p></div>}
        <div className={styles.control2}><SectionTitle>当前步骤</SectionTitle><p className={styles.text5}>{run.status === "completed" ? "所有步骤已完成" : run.flow.steps[run.current]?.label || "等待执行"}</p><p className={[styles.caption7, muted].filter(Boolean).join(" ")}>{run.status === "waiting" ? "当前步骤等待确认，请按执行要求检查后继续。" : run.status === "failed" ? "本次步骤执行失败，输入与已完成记录已保留。请查看错误后重试。" : run.status === "completed" ? "交付文档和执行记录可在下方查看。" : run.status === "stopped" ? "本次运行已停止，输入与执行记录已保留。" : "团队正在执行，你可以查看过程记录。"}</p></div>
        {run.error && <div className={styles.grid1}><p role="alert" className={styles.caption8}>{run.error}</p>{currentSessionUrl && <VRouteLinkButton to={currentSessionUrl} variant="ghost">打开原生会话</VRouteLinkButton>}</div>}<p className={[styles.caption4, muted].filter(Boolean).join(" ")}>运行使用启动时保存的流程，后续设计修改留在草稿中。</p>
      </> : <><p className={[styles.text6, muted].filter(Boolean).join(" ")}>开始一次运行，填写这条流程定义的输入。</p><div className={styles.grid5}>{displayedFlow.fields.map(item => <div key={item.id} className={styles.row3}><span>{item.label}</span><span className={[styles.caption5, muted].filter(Boolean).join(" ")}>{item.required ? "必填" : "选填"}</span></div>)}</div></>}
    </div>
    <div className={styles.row4}>
      {mode === "design" ? <><VButton variant="primary" density="normal" className={[primary, styles.row5].filter(Boolean).join(" ")} isPending={workspace.saving} isDisabled={workspace.saving || workspace.pending} onClick={() => save()} icon={<Save size={14}/>}>保存流程</VButton>{step && step.kind !== "input" && step.kind !== "output" && <><VButton aria-label="上移步骤" onClick={() => moveStep(-1)} isIconOnly><ArrowUp size={14}/></VButton><VButton aria-label="下移步骤" onClick={() => moveStep(1)} isIconOnly><ArrowDown size={14}/></VButton><VButton aria-label="删除步骤" onClick={() => setDeleteStepId(selectedId)} isIconOnly><Trash2 size={14}/></VButton></>}</> : run?.status === "waiting" ? <><VButton density="normal" variant="primary" className={[primary, styles.row6].filter(Boolean).join(" ")} isPending={workspace.pending} isDisabled={workspace.pending} onClick={confirmRun} icon={<Check size={15}/>}>确认并继续</VButton><VButton density="normal" isDisabled={workspace.pending} onClick={() => void workspace.command("revise")}>退回补充</VButton></> : run?.status === "failed" ? <VButton density="normal" variant="primary" className={[primary, styles.control3].filter(Boolean).join(" ")} isPending={workspace.pending} isDisabled={workspace.pending} onClick={() => void workspace.command("retry")}>重试当前步骤</VButton> : run?.status === "completed" ? <VButton density="normal" variant="primary" className={[primary, styles.control3].filter(Boolean).join(" ")} onClick={() => setShowArtifact(true)} icon={<FileText size={14}/>}>查看交付文档</VButton> : !active ? <VButton density="normal" variant="primary" className={[primary, styles.control3].filter(Boolean).join(" ")} onClick={openRun} icon={<Play size={14}/>}>开始新运行</VButton> : <span className={[styles.caption5, muted].filter(Boolean).join(" ")}>执行记录会随流程更新</span>}
    </div>
  </div>;
    return <><WorkbenchShell flows={flows} flow={flow} run={run} runs={runs} mode={mode} selectedId={selectedId} dirty={dirty} inspector={inspector} notice={notice} teamId={team.teamId} teams={teams} onTeam={onTeam} members={members} onDiscussion={onDiscussion} onHistory={onHistory} saving={workspace.saving} pending={workspace.pending} loading={workspace.loading} error={workspace.error} onReload={workspace.reload} inspectorOpen={inspectorOpen} onInspectorOpen={setInspectorOpen} onMode={value => { setMode(value); setInspectorOpen(false); }} onFlow={selectFlow} onStep={setSelectedId} onRun={id => { const item = runs.find(entry => entry.id === id); workspace.selectRun(id); setSelectedId(item?.flow.steps[Math.min(item.current, item.flow.steps.length - 1)]?.id || "input"); }} onSave={() => save()} onStart={openRun} onStop={() => void workspace.command("stop")} onCreate={() => { setNewName(""); setCreateTemplate("blank"); setShowCreate(true); }} onAddStep={() => { setStepName(""); setShowAddStep(true); }} onMembers={() => setShowMembers(true)} onArtifact={() => setShowArtifact(true)} onDismiss={() => setNotice("")}/>
    <VDialog className={styles.control4} open={Boolean(launchFlow)} onOpenChange={open => { if (!open)
        setLaunchFlow(null); }} title="开始一次运行" description={launchFlow?.name} size="lg" footer={<><VButton density="normal" onClick={() => setLaunchFlow(null)}>取消</VButton><VButton type="submit" form="launch-form" density="normal" variant="primary" className={primary} isPending={workspace.pending} isDisabled={workspace.pending} icon={<Play size={14}/>}>开始运行</VButton></>}>
      <form id="launch-form" onSubmit={event => { event.preventDefault(); startRun(); }} className={styles.grid6}>
        {launchFlow?.fields.map(item => <div key={item.id} className={styles.grid5}><label htmlFor={`run-${item.id}`} className={styles.text7}>{item.label}{item.required && <span className={styles.text8} aria-label="必填">*</span>}</label>{item.kind === "paragraph" ? <VTextarea id={`run-${item.id}`} aria-label={item.label} aria-required={item.required} value={values[item.id] || ""} onChange={event => updateValue(item.id, event.target.value)} rows={4} placeholder={`请输入${item.label}`} className={styles.text9}/> : item.kind === "select" ? <VSelect id={`run-${item.id}`} aria-label={item.label} selectedKey={values[item.id] || null} placeholder={`请选择${item.label}`} options={item.options.map(option => ({ id: option, label: option }))} onSelectionChange={key => updateValue(item.id, String(key))}/> : <VInput id={`run-${item.id}`} aria-label={item.label} aria-required={item.required} value={values[item.id] || ""} onChange={event => updateValue(item.id, event.target.value)} placeholder={`请输入${item.label}`} className={field}/>}</div>)}
        {launchFlow?.fields.length === 0 && <p className={[styles.text6, muted].filter(Boolean).join(" ")}>此流程无需额外输入，可以直接开始。</p>}
        {(formError || workspace.error) && <p role="alert" className={styles.surface3}>{formError || workspace.error}</p>}
      </form>
    </VDialog>
    <VDialog className={styles.control4} open={showCreate} onOpenChange={setShowCreate} title="创建你的流程" description="定义入口、协作步骤和交付结果。" footer={<><VButton onClick={() => setShowCreate(false)}>取消</VButton><VButton variant="primary" className={primary} isDisabled={!newName.trim()} disabledReason="请先填写流程名称" onClick={createFlow}>创建流程</VButton></>}><div className={styles.grid6}><Field label="流程名称"><VInput aria-label="流程名称" value={newName} onChange={event => setNewName(event.target.value)} placeholder="给流程起一个名字" className={field}/></Field><Field label="起点"><VSelect aria-label="流程起点" selectedKey={createTemplate} onSelectionChange={key => setCreateTemplate(String(key))} options={workflowTemplateOptions}/></Field></div></VDialog>
    <VDialog className={styles.control4} open={showAddStep} onOpenChange={setShowAddStep} title="添加步骤" description="配置后，步骤会加入当前流程。" footer={<><VButton onClick={() => setShowAddStep(false)}>取消</VButton><VButton variant="primary" className={primary} isDisabled={!stepName.trim()} disabledReason="请先填写步骤名称" onClick={addStep}>添加步骤</VButton></>}><div className={styles.grid6}><Field label="步骤名称"><VInput aria-label="新步骤名称" value={stepName} onChange={event => setStepName(event.target.value)} placeholder="例如：核对数据" className={field}/></Field><Field label="步骤类型"><VSelect aria-label="新步骤类型" selectedKey={stepKind} onSelectionChange={key => setStepKind(key as "agent" | "human")} options={[{ id: "agent", label: "Agent 任务" }, { id: "human", label: "人工确认" }]}/></Field></div></VDialog>
    <VDialog className={styles.control4} open={showMembers} onOpenChange={setShowMembers} title="团队成员" description="这些成员可以被分配到不同步骤。"><div className={styles.grid6}>{MEMBERS.map(member => <div key={member.id} className={styles.row7}><span className={styles.grid7}>{member.initial}</span><div><p className={styles.text7}>{member.name}</p><p className={[styles.caption6, muted].filter(Boolean).join(" ")}>{member.detail}</p></div></div>)}</div></VDialog>
    <VConfirmDialog open={Boolean(deleteStepId)} onOpenChange={open => { if (!open)
        setDeleteStepId(""); }} title="删除步骤" description="删除后需要重新添加才能恢复。已保存的运行记录不会改变。" confirmLabel="删除步骤" onConfirm={() => { editFlow(current => ({ ...current, steps: current.steps.filter(item => item.id !== deleteStepId) })); setSelectedId("input"); setDeleteStepId(""); }}/>
    <WorkflowArtifactDialog teamId={team.teamId} run={run} open={showArtifact} onOpenChange={setShowArtifact}/>
  </>;
}
