import { useEffect, useState, type ReactNode } from "react";
import { ArrowDown, ArrowUp, Check, FileText, Play, Plus, Save, Trash2 } from "lucide-react";
import { VButton, VCheckbox, VDialog, VInput, VSelect, VTextarea } from "../../src/components/vui";
import { WorkbenchShell } from "./WorkbenchShell";
import { copyFlow, EXAMPLE_FLOWS, KIND_LABEL, MEMBERS, ownerName, type Flow, type InputField, type Run, type Step, type StepKind } from "./fixtures";

const primary = "!border-[#256c58] !bg-[#256c58] !text-white hover:!bg-[#1d5848]";
const fieldClass = "!h-9 !text-sm";
const muted = "text-[var(--fg-secondary)]";
const statusLabel = { running: "运行中", waiting: "等待确认", completed: "已完成", failed: "执行失败", stopped: "已停止" } as const;
function SectionTitle({ children, extra }: { children: ReactNode; extra?: ReactNode }) {
  return <div className="flex min-w-0 items-center justify-between gap-2"><h3 className="text-sm font-semibold text-[var(--fg-primary)]">{children}</h3>{extra}</div>;
}
function Field({ label, children }: { label: string; children: ReactNode }) {
  return <div className="grid min-w-0 gap-2"><div className="text-xs font-medium text-[var(--fg-secondary)]">{label}</div>{children}</div>;
}

export function App() {
  const [flows, setFlows] = useState<Flow[]>(() => EXAMPLE_FLOWS.map(copyFlow));
  const [flowId, setFlowId] = useState("analysis");
  const [mode, setMode] = useState<"design" | "run">("design");
  const [selectedId, setSelectedId] = useState("");
  const [dirtyIds, setDirtyIds] = useState<string[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [runId, setRunId] = useState<string | null>(null);
  const [launchFlow, setLaunchFlow] = useState<Flow | null>(null);
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
  const [inspectorOpen, setInspectorOpen] = useState(false);
  const flow = flows.find(item => item.id === flowId);
  const run = runs.find(item => item.id === runId && item.flow.id === flowId);
  const displayedFlow = mode === "run" && run ? run.flow : flow;
  const step = displayedFlow?.steps.find(item => item.id === selectedId) ?? displayedFlow?.steps[0];
  const dirty = dirtyIds.includes(flowId);
  const active = run?.status === "running" || run?.status === "waiting";

  useEffect(() => {
    if (!runs.some(item => item.status === "running")) return;
    const timer = window.setTimeout(() => setRuns(current => current.map(item => {
      if (item.status !== "running") return item;
      const next = item.current + 1;
      if (next >= item.flow.steps.length) return { ...item, current: next, status: "completed", messages: [...item.messages, `${ownerName(item.flow.steps.at(-1)?.owner || "团队")} · 本次流程已完成，交付结果已准备好。`] };
      const nextStep = item.flow.steps[next];
      return { ...item, current: next, status: nextStep.kind === "human" ? "waiting" : "running", messages: [...item.messages, `${ownerName(nextStep.owner)} · ${nextStep.kind === "human" ? `已到达「${nextStep.label}」，请确认后继续。` : `正在${nextStep.label}。`}`] };
    })), 1700);
    return () => window.clearTimeout(timer);
  }, [runs]);

  function editFlow(update: (current: Flow) => Flow) {
    setFlows(current => current.map(item => item.id === flowId ? update(item) : item));
    setDirtyIds(current => current.includes(flowId) ? current : [...current, flowId]);
  }
  function editStep(patch: Partial<Step>) { editFlow(current => ({ ...current, steps: current.steps.map(item => item.id === (selectedId || current.steps[0]?.id) ? { ...item, ...patch } : item) })); }
  function editField(id: string, patch: Partial<InputField>) { editFlow(current => ({ ...current, fields: current.fields.map(item => item.id === id ? { ...item, ...patch } : item) })); }
  function save(showNotice = true) { setDirtyIds(current => current.filter(id => id !== flowId)); if (showNotice) setNotice("流程已保存到本次预览。"); }
  function selectFlow(id: string) { setFlowId(id); setSelectedId(""); setRunId(null); setNotice(""); setInspectorOpen(false); }
  function openRun() { if (!flow) return; save(false); setLaunchFlow(copyFlow(flow)); setValues({}); setFormError(""); }
  function startRun() {
    if (!launchFlow) return;
    const missing = launchFlow.fields.filter(item => item.required && !(values[item.id] || "").trim());
    if (missing.length) { setFormError(`请填写：${missing.map(item => item.label).join("、")}`); return; }
    const id = `run-${Date.now()}`;
    const first = Math.min(1, launchFlow.steps.length - 1);
    setRuns(current => [{ id, flow: copyFlow(launchFlow), values: { ...values }, status: launchFlow.steps[first]?.kind === "human" ? "waiting" : "running", current: first, messages: ["用户 · 已提交本次运行输入。", "协调记录 · 已开始执行此流程。"] }, ...current]);
    setRunId(id); setMode("run"); setLaunchFlow(null); setSelectedId(launchFlow.steps[first]?.id ?? "input"); setInspectorOpen(false);
  }
  function updateRun(update: (current: Run) => Run) { setRuns(current => current.map(item => item.id === runId ? update(item) : item)); }
  function confirmRun() {
    if (!run || run.status !== "waiting") return;
    updateRun(current => ({ ...current, status: current.flow.steps[current.current + 1]?.kind === "human" ? "waiting" : "running", current: current.current + 1, messages: [...current.messages, "用户 · 已确认，继续下一步骤。"] }));
    setSelectedId(run.flow.steps[run.current + 1]?.id ?? "deliver");
  }
  function addField() {
    const id = `field-${Date.now()}`;
    editFlow(current => ({ ...current, fields: [...current.fields, { id, label: "新输入项", kind: "text", required: false, options: [] }] }));
  }
  function createFlow() {
    if (!newName.trim()) return;
    const id = `flow-${Date.now()}`;
    const base = EXAMPLE_FLOWS.find(item => item.id === createTemplate);
    const item: Flow = base ? { ...copyFlow(base), id, name: newName.trim() } : { id, name: newName.trim(), description: "", fields: [], steps: [
      { id: "input", label: "接收输入", kind: "input", owner: "用户", instruction: "" },
      { id: "deliver", label: "交付结果", kind: "output", owner: "writer", instruction: "" },
    ] };
    setFlows(current => [...current, item]); setDirtyIds(current => [...current, id]); selectFlow(id); setMode("design"); setShowCreate(false);
  }
  function addStep() {
    if (!stepName.trim()) return;
    const id = `step-${Date.now()}`;
    editFlow(current => { const steps = [...current.steps]; steps.splice(Math.max(1, steps.length - 1), 0, { id, label: stepName.trim(), kind: stepKind, owner: stepKind === "human" ? "用户" : "analyst", instruction: "" }); return { ...current, steps }; });
    setSelectedId(id); setShowAddStep(false); setInspectorOpen(true);
  }
  function moveStep(direction: -1 | 1) {
    editFlow(current => { const steps = [...current.steps]; const index = steps.findIndex(item => item.id === selectedId); const target = index + direction; if (index < 1 || target < 1 || target >= steps.length - 1) return current; [steps[index], steps[target]] = [steps[target], steps[index]]; return { ...current, steps }; });
  }
  function previewScene(scene: string) {
    setNotice(""); setInspectorOpen(false);
    if (scene === "empty") { setFlowId(""); setRunId(null); return; }
    const current = flow ?? flows[0]; if (!current) return;
    setFlowId(current.id);
    if (scene === "design") { setMode("design"); setSelectedId(""); return; }
    const status = scene === "waiting" ? "waiting" : scene === "failed" ? "failed" : "completed";
    const currentIndex = status === "waiting" ? current.steps.findIndex(item => item.kind === "human") : status === "failed" ? Math.min(2, current.steps.length - 1) : current.steps.length;
    if (currentIndex < 0) { setNotice("这条流程没有人工确认步骤，可以在设计流程中添加。"); return; }
    const id = `preview-${Date.now()}`;
    const preview: Run = { id, flow: copyFlow(current), values: Object.fromEntries(current.fields.map(item => [item.id, item.kind === "select" ? item.options[0] || "" : "本次任务的示例输入"])), status, current: currentIndex, messages: ["分析员 · 已整理相关材料与来源。", "复核员 · 已标记需要确认的内容。", status === "failed" ? "执行记录 · 来源暂不可用，本次执行已暂停。" : "撰写员 · 初稿已准备好。"] };
    setRuns(items => [preview, ...items]); setRunId(id); setMode("run"); setSelectedId(current.steps[Math.min(currentIndex, current.steps.length - 1)]?.id ?? "input");
  }

  const inspector = displayedFlow && <div className="flex h-full min-h-0 flex-col">
    <div className="border-b border-black/5 px-5 py-4"><div className={`mb-1 text-xs ${muted}`}>{mode === "design" ? "节点配置" : "运行详情"}</div><h2 className="text-base font-semibold">{mode === "design" ? step?.label ?? "流程配置" : run ? statusLabel[run.status] : "准备运行"}</h2></div>
    <div className="grid min-h-0 flex-1 content-start gap-5 overflow-auto p-5">
      {mode === "design" && step ? <>
        <Field label="步骤名称"><VInput aria-label="步骤名称" value={step.label} onChange={event => editStep({ label: event.target.value })} className={fieldClass} /></Field>
        <div className="flex items-center gap-2 text-xs"><span className={`rounded-md bg-slate-100 px-2 py-1 ${muted}`}>{KIND_LABEL[step.kind]}</span></div>
        {step.kind === "input" ? <>
          <SectionTitle extra={<VButton variant="ghost" onClick={addField} icon={<Plus size={14} />}>添加输入</VButton>}>运行时收集</SectionTitle>
          {displayedFlow.fields.length === 0 && <p className={`text-xs leading-6 ${muted}`}>可以直接运行，也可以添加这条流程需要的信息。</p>}
          {displayedFlow.fields.map((item, index) => <div key={item.id} className="grid gap-3 rounded-lg border border-slate-200 bg-slate-50/60 p-3">
            <div className="flex items-center justify-between"><span className={`text-xs ${muted}`}>输入 {index + 1}</span><VButton variant="ghost" isIconOnly aria-label={`删除输入${index + 1}`} onClick={() => editFlow(current => ({ ...current, fields: current.fields.filter(field => field.id !== item.id) }))}><Trash2 size={13} /></VButton></div>
            <VInput aria-label={`输入${index + 1}名称`} value={item.label} onChange={event => editField(item.id, { label: event.target.value })} className={fieldClass} />
            <VSelect aria-label={`输入${index + 1}类型`} selectedKey={item.kind} options={[{ id: "text", label: "单行文本" }, { id: "paragraph", label: "多行文本" }, { id: "select", label: "下拉选择" }]} onSelectionChange={key => editField(item.id, { kind: key as InputField["kind"], options: key === "select" && !item.options.length ? ["选项一", "选项二"] : item.options })} />
            {item.kind === "select" && <VInput aria-label={`输入${index + 1}选项`} placeholder="选项，以中文逗号分隔" value={optionDrafts[`${flowId}:${item.id}`] ?? item.options.join("，")} onChange={event => { const text = event.target.value; setOptionDrafts(current => ({ ...current, [`${flowId}:${item.id}`]: text })); editField(item.id, { options: text.split(/[，,]/).map(value => value.trim()).filter(Boolean) }); }} className={fieldClass} />}
            <VCheckbox isSelected={item.required} onChange={required => editField(item.id, { required })}>必填</VCheckbox>
          </div>)}
        </> : <>
          {step.kind !== "human" && <Field label="负责成员"><VSelect aria-label="负责成员" selectedKey={step.owner} onSelectionChange={key => editStep({ owner: String(key) })} options={MEMBERS.map(item => ({ id: item.id, label: item.name }))} /></Field>}
          <Field label={step.kind === "human" ? "确认说明" : "执行要求"}><VTextarea aria-label="步骤要求" value={step.instruction} rows={5} onChange={event => editStep({ instruction: event.target.value })} className="!text-sm leading-6" /></Field>
          <p className={`text-xs leading-6 ${muted}`}>{step.kind === "human" ? "流程到达这里时暂停，等待用户确认后继续。" : "此步骤使用本次运行的输入，以及前序步骤的结果。"}</p>
        </>}
      </> : mode === "run" && run ? <>
        <div><SectionTitle>本次任务</SectionTitle><dl className="mt-3 grid gap-3">{run.flow.fields.map(item => <div key={item.id}><dt className={`text-xs ${muted}`}>{item.label}</dt><dd className="mt-1 break-words text-sm leading-6">{run.values[item.id] || "未填写"}</dd></div>)}</dl></div>
        {step && <div className="border-t border-black/5 pt-4"><SectionTitle>所选步骤</SectionTitle><p className="mt-3 text-sm font-medium">{step.label}</p><p className={`mt-1 text-xs ${muted}`}>{KIND_LABEL[step.kind]} · {ownerName(step.owner)}</p><p className={`mt-2 text-xs leading-6 ${muted}`}>{step.instruction || "此步骤没有额外执行要求。"}</p></div>}
        <div className="border-t border-black/5 pt-4"><SectionTitle>当前步骤</SectionTitle><p className="mt-3 text-sm font-medium">{run.status === "completed" ? "所有步骤已完成" : run.flow.steps[run.current]?.label || "等待执行"}</p><p className={`mt-2 text-xs leading-6 ${muted}`}>{run.status === "waiting" ? "初稿已整理完成，请确认是否继续交付。" : run.status === "failed" ? "读取来源时连接中断。输入与已完成结果已保留，可以重试。" : run.status === "completed" ? "交付文档和执行记录可在下方查看。" : run.status === "stopped" ? "本次运行已停止，输入与执行记录已保留。" : "团队正在执行，你可以查看过程记录。"}</p></div>
        <p className={`text-xs leading-6 ${muted}`}>运行使用启动时保存的流程，后续设计修改留在草稿中。</p>
      </> : <><p className={`text-sm leading-7 ${muted}`}>开始一次运行，填写这条流程定义的输入。</p><div className="grid gap-2">{displayedFlow.fields.map(item => <div key={item.id} className="flex items-center justify-between rounded-lg bg-slate-50 px-3 py-3 text-sm"><span>{item.label}</span><span className={`text-xs ${muted}`}>{item.required ? "必填" : "选填"}</span></div>)}</div></>}
    </div>
    <div className="flex shrink-0 flex-wrap gap-2 border-t border-black/5 p-4">
      {mode === "design" ? <><VButton variant="primary" density="normal" className={`${primary} !h-10 !min-h-10 flex-1`} onClick={() => save()} icon={<Save size={14} />}>保存流程</VButton>{step && step.kind !== "input" && step.kind !== "output" && <><VButton aria-label="上移步骤" onClick={() => moveStep(-1)} isIconOnly><ArrowUp size={14} /></VButton><VButton aria-label="下移步骤" onClick={() => moveStep(1)} isIconOnly><ArrowDown size={14} /></VButton><VButton aria-label="删除步骤" onClick={() => { editFlow(current => ({ ...current, steps: current.steps.filter(item => item.id !== selectedId) })); setSelectedId("input"); }} isIconOnly><Trash2 size={14} /></VButton></>}</> : run?.status === "waiting" ? <><VButton density="normal" variant="primary" className={`${primary} flex-1`} onClick={confirmRun} icon={<Check size={15} />}>确认并继续</VButton><VButton density="normal" onClick={() => updateRun(current => ({ ...current, status: "running", current: Math.max(1, current.current - 1), messages: [...current.messages, "用户 · 请补充材料后再次确认。"] }))}>退回补充</VButton></> : run?.status === "failed" ? <VButton density="normal" variant="primary" className={`${primary} w-full`} onClick={() => updateRun(current => ({ ...current, status: "running", messages: [...current.messages, "用户 · 已重试当前步骤。"] }))}>重试当前步骤</VButton> : run?.status === "completed" ? <VButton density="normal" variant="primary" className={`${primary} w-full`} onClick={() => setShowArtifact(true)} icon={<FileText size={14} />}>查看交付文档</VButton> : !active ? <VButton density="normal" variant="primary" className={`${primary} w-full`} onClick={openRun} icon={<Play size={14} />}>开始新运行</VButton> : <span className={`text-xs ${muted}`}>执行记录会随流程更新</span>}
    </div>
  </div>;

  return <><WorkbenchShell flows={flows} flow={flow} run={run} runs={runs} mode={mode} selectedId={selectedId} dirty={dirty} inspector={inspector} notice={notice} inspectorOpen={inspectorOpen} onInspectorOpen={setInspectorOpen}
    onMode={setMode} onFlow={selectFlow} onStep={setSelectedId}
    onRun={id => { const item = runs.find(entry => entry.id === id); setRunId(id); setSelectedId(item?.flow.steps[Math.min(item.current, item.flow.steps.length - 1)]?.id || "input"); }}
    onSave={() => save()} onStart={openRun}
    onStop={() => updateRun(current => ({ ...current, status: "stopped", messages: [...current.messages, "用户 · 已停止本次运行。"] }))}
    onCreate={() => { setNewName(""); setCreateTemplate("blank"); setShowCreate(true); }}
    onAddStep={() => { setStepName(""); setShowAddStep(true); }} onMembers={() => setShowMembers(true)}
    onArtifact={() => setShowArtifact(true)} onDismiss={() => setNotice("")} onScene={previewScene} />
    <VDialog className="max-sm:[&_button]:!min-h-11 max-sm:[&_[aria-label=Close]]:!min-w-11" open={Boolean(launchFlow)} onOpenChange={open => { if (!open) setLaunchFlow(null); }} title="开始一次运行" description={launchFlow?.name} size="lg" footer={<><VButton density="normal" onClick={() => setLaunchFlow(null)}>取消</VButton><VButton type="submit" form="launch-form" density="normal" variant="primary" className={primary} icon={<Play size={14} />}>开始运行</VButton></>}>
      <form id="launch-form" onSubmit={event => { event.preventDefault(); startRun(); }} className="grid gap-5 py-2">
        {launchFlow?.fields.map(item => <div key={item.id} className="grid gap-2"><label htmlFor={`run-${item.id}`} className="text-sm font-medium">{item.label}{item.required && <span className="ml-1 text-rose-500" aria-label="必填">*</span>}</label>{item.kind === "paragraph" ? <VTextarea id={`run-${item.id}`} aria-label={item.label} aria-required={item.required} value={values[item.id] || ""} onChange={event => setValues(current => ({ ...current, [item.id]: event.target.value }))} rows={4} placeholder={`请输入${item.label}`} className="!text-sm" /> : item.kind === "select" ? <VSelect id={`run-${item.id}`} aria-label={item.label} selectedKey={values[item.id] || null} placeholder={`请选择${item.label}`} options={item.options.map(option => ({ id: option, label: option }))} onSelectionChange={key => setValues(current => ({ ...current, [item.id]: String(key) }))} /> : <VInput id={`run-${item.id}`} aria-label={item.label} aria-required={item.required} value={values[item.id] || ""} onChange={event => setValues(current => ({ ...current, [item.id]: event.target.value }))} placeholder={`请输入${item.label}`} className={fieldClass} />}</div>)}
        {launchFlow?.fields.length === 0 && <p className={`text-sm leading-7 ${muted}`}>此流程无需额外输入，可以直接开始。</p>}
        {formError && <p role="alert" className="rounded-lg bg-rose-50 p-3 text-sm text-rose-700">{formError}</p>}
      </form>
    </VDialog>
    <VDialog className="max-sm:[&_button]:!min-h-11 max-sm:[&_[aria-label=Close]]:!min-w-11" open={showCreate} onOpenChange={setShowCreate} title="创建你的流程" description="定义入口、协作步骤和交付结果。" footer={<><VButton onClick={() => setShowCreate(false)}>取消</VButton><VButton variant="primary" className={primary} isDisabled={!newName.trim()} disabledReason="请先填写流程名称" onClick={createFlow}>创建流程</VButton></>}><div className="grid gap-5 py-2"><Field label="流程名称"><VInput aria-label="流程名称" value={newName} onChange={event => setNewName(event.target.value)} placeholder="给流程起一个名字" className={fieldClass} /></Field><Field label="起点"><VSelect aria-label="流程起点" selectedKey={createTemplate} onSelectionChange={key => setCreateTemplate(String(key))} options={[{ id: "blank", label: "空白流程" }, ...EXAMPLE_FLOWS.map(item => ({ id: item.id, label: `${item.name}模板` }))]} /></Field></div></VDialog>
    <VDialog className="max-sm:[&_button]:!min-h-11 max-sm:[&_[aria-label=Close]]:!min-w-11" open={showAddStep} onOpenChange={setShowAddStep} title="添加步骤" description="配置后，步骤会加入当前流程。" footer={<><VButton onClick={() => setShowAddStep(false)}>取消</VButton><VButton variant="primary" className={primary} isDisabled={!stepName.trim()} disabledReason="请先填写步骤名称" onClick={addStep}>添加步骤</VButton></>}><div className="grid gap-5 py-2"><Field label="步骤名称"><VInput aria-label="新步骤名称" value={stepName} onChange={event => setStepName(event.target.value)} placeholder="例如：核对数据" className={fieldClass} /></Field><Field label="步骤类型"><VSelect aria-label="新步骤类型" selectedKey={stepKind} onSelectionChange={key => setStepKind(key as "agent" | "human")} options={[{ id: "agent", label: "Agent 任务" }, { id: "human", label: "人工确认" }]} /></Field></div></VDialog>
    <VDialog className="max-sm:[&_button]:!min-h-11 max-sm:[&_[aria-label=Close]]:!min-w-11" open={showMembers} onOpenChange={setShowMembers} title="团队成员" description="这些成员可以被分配到不同步骤。"><div className="grid gap-5 py-2">{MEMBERS.map(member => <div key={member.id} className="flex items-center gap-3"><span className="grid h-10 w-10 place-items-center rounded-full bg-slate-100 text-sm">{member.initial}</span><div><p className="text-sm font-medium">{member.name}</p><p className={`mt-1 text-xs ${muted}`}>{member.detail}</p></div></div>)}</div></VDialog>
    <VDialog className="max-sm:[&_button]:!min-h-11 max-sm:[&_[aria-label=Close]]:!min-w-11" open={showArtifact} onOpenChange={setShowArtifact} title={run ? `${run.flow.name} · ${run.status === "waiting" ? "初稿" : "交付文档"}` : "文档预览"} description="示例产物，仅用于检查阅读和确认体验。" size="lg" footer={<><VButton onClick={() => setShowArtifact(false)}>返回工作台</VButton>{run?.status === "waiting" && <VButton variant="primary" className={primary} onClick={() => { confirmRun(); setShowArtifact(false); }}>确认并继续</VButton>}</>}><article className="grid gap-5 py-3 text-sm leading-7"><h2 className="text-lg font-semibold">结果摘要</h2><p>本次输入已整理为可追溯的材料，分析与复核意见已汇总。正式接入后，这里展示流程实际生成的文档。</p><h3 className="font-semibold">本次输入</h3>{run?.flow.fields.map(item => <p key={item.id}><strong>{item.label}：</strong>{run.values[item.id] || "未填写"}</p>)}<h3 className="font-semibold">待确认事项</h3><p>检查资料范围是否完整、关键判断是否有来源支持，再决定继续交付或退回补充。</p></article></VDialog>
  </>;
}
