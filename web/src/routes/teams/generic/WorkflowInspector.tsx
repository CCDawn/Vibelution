import { useState, type ReactNode } from "react";
import { ArrowDown, ArrowUp, Plus, Save, Trash2 } from "lucide-react";
import { VButton, VCheckbox, VInput, VSelect, VSkeleton, VTextarea } from "../../../components/vui";
import { KIND_LABEL, type Flow, type InputField, type Step, type WorkflowMember } from "./workflowModel";
import styles from "./WorkflowInspector.styles";

const field = styles.text1;
const muted = styles.text2;
function PendingSlot({ loading, children }: { loading?: boolean; children: ReactNode }) {
  return <div className={styles.slot}><div className={loading ? styles.hidden : undefined}>{children}</div>{loading && <VSkeleton shape="block" className={styles.fill}/>}</div>;
}
function Field({ label, children }: { label: string; children: ReactNode }) {
  return <div className={styles.grid1}><div className={styles.caption1}>{label}</div>{children}</div>;
}
function SectionTitle({ children, extra }: { children: ReactNode; extra?: ReactNode }) {
  return <div className={styles.row1}><h3 className={styles.heading1}>{children}</h3>{extra}</div>;
}
export function WorkflowInspectorFrame({ title, detail, footer, children, loading }: {
  title: string; detail: string; footer: ReactNode; children: ReactNode; loading?: boolean;
}) {
  return <div data-team-inspector aria-hidden={loading || undefined} className={styles.frame}>
    <div data-team-inspector-header className={styles.header}><h2 className={styles.title}>{title}</h2><span className={styles.detail}>{detail}</span></div>
    <div data-team-inspector-body className={styles.body}>{children}</div>
    <div data-team-inspector-footer className={styles.footer}>{footer}</div>
  </div>;
}
export function WorkflowDesignFields({ flow, step, members, loading, onStep, onField, onAddField, onRemoveField }: {
  flow: Flow; step: Step; members: WorkflowMember[]; loading?: boolean;
  onStep: (patch: Partial<Step>) => void; onField: (id: string, patch: Partial<InputField>) => void;
  onAddField: () => void; onRemoveField: (id: string) => void;
}) {
  const [optionDrafts, setOptionDrafts] = useState<Record<string, string>>({});
  return <>
        <Field label="步骤名称"><PendingSlot loading={loading}><VInput aria-label="步骤名称" value={step.label} onChange={event => onStep({ label: event.target.value })} className={field}/></PendingSlot></Field>
        {step.kind === "input" ? <>
          <SectionTitle extra={<VButton variant="ghost" onClick={onAddField} icon={<Plus size={14}/>}>添加输入</VButton>}>运行时收集</SectionTitle>
          {flow.fields.length === 0 && <p className={[styles.caption4, muted].filter(Boolean).join(" ")}>可以直接运行，也可以添加这条流程需要的信息。</p>}
          {flow.fields.map((item, index) => <div key={item.id} className={styles.grid3}>
            <div className={styles.row2}><span className={[styles.caption5, muted].filter(Boolean).join(" ")}>输入 {index + 1}</span><VButton variant="ghost" isIconOnly aria-label={`删除输入${index + 1}`} onClick={() => onRemoveField(item.id)}><Trash2 size={13}/></VButton></div>
            <PendingSlot loading={loading}><VInput aria-label={`输入${index + 1}名称`} value={item.label} onChange={event => onField(item.id, { label: event.target.value })} className={field}/></PendingSlot>
            <PendingSlot loading={loading}><VSelect aria-label={`输入${index + 1}类型`} selectedKey={item.kind} options={[{ id: "text", label: "单行文本" }, { id: "paragraph", label: "多行文本" }, { id: "select", label: "下拉选择" }]} onSelectionChange={key => { setOptionDrafts(current => { const next = { ...current }; delete next[`${flow.id}:${item.id}`]; return next; }); onField(item.id, { kind: key as InputField["kind"], options: key === "select" ? item.options.length ? item.options : ["选项一", "选项二"] : [] }); }}/></PendingSlot>
            {item.kind === "select" && <PendingSlot loading={loading}><VInput aria-label={`输入${index + 1}选项`} placeholder="选项，以中文逗号分隔" value={optionDrafts[`${flow.id}:${item.id}`] ?? item.options.join("，")} onChange={event => { const text = event.target.value; setOptionDrafts(current => ({ ...current, [`${flow.id}:${item.id}`]: text })); onField(item.id, { options: text.split(/[，,]/).map(value => value.trim()).filter(Boolean) }); }} className={field}/></PendingSlot>}
            <PendingSlot loading={loading}><VCheckbox isSelected={item.required} onChange={required => onField(item.id, { required })}>必填</VCheckbox></PendingSlot>
          </div>)}
        </> : <>
          {step.kind !== "human" && <Field label="负责成员"><PendingSlot loading={loading}><VSelect aria-label="负责成员" selectedKey={step.owner || "__collect__"} onSelectionChange={key => onStep({ owner: key === "__collect__" ? "" : String(key) })} options={[...(step.kind === "output" ? [{ id: "__collect__", label: "直接交付已有结果" }] : []), ...members.map(item => ({ id: item.id, label: item.available ? item.name : `${item.name}（不可用）`, disabled: !item.available }))]}/></PendingSlot></Field>}
          <Field label={step.kind === "human" ? "确认说明" : "执行要求"}><PendingSlot loading={loading}><VTextarea aria-label="步骤要求" value={step.instruction} rows={5} onChange={event => onStep({ instruction: event.target.value })} className={styles.text3}/></PendingSlot></Field>
          <p className={[styles.caption4, muted].filter(Boolean).join(" ")}>{step.kind === "human" ? "流程到达这里时暂停，等待用户确认后继续。" : "此步骤使用本次运行的输入，以及前序步骤的结果。"}</p>
        </>}

  </>;
}
export function WorkflowDesignFooter({ step, saving, dirty, pending, loading, onSave, onMove, onDelete }: {
  step?: Step; saving?: boolean; dirty?: boolean; pending?: boolean; loading?: boolean;
  onSave: () => void; onMove: (direction: -1 | 1) => void; onDelete: () => void;
}) {
  return <><span className={styles.saveStatus}>{loading ? <><span className={styles.hidden}>流程已保存</span><VSkeleton className={styles.fill}/></> : saving ? "正在保存…" : dirty ? "更改尚未保存" : "流程已保存"}</span>
    <VButton variant="secondary" density="normal" className={styles.mobileSave} isPending={saving} isDisabled={loading || saving || pending} onClick={onSave} icon={<Save size={14}/>}>保存流程</VButton>
    {step && step.kind !== "input" && step.kind !== "output" && <><VButton aria-label="上移步骤" onClick={() => onMove(-1)} isIconOnly><ArrowUp size={14}/></VButton><VButton aria-label="下移步骤" onClick={() => onMove(1)} isIconOnly><ArrowDown size={14}/></VButton><VButton aria-label="删除步骤" onClick={onDelete} isIconOnly><Trash2 size={14}/></VButton></>}
  </>;
}
const noop = () => undefined;
export function WorkflowInspectorLoading({ flow }: { flow: Flow }) {
  const step = flow.steps[0];
  return <WorkflowInspectorFrame loading title="节点配置" detail={step ? KIND_LABEL[step.kind] : "流程配置"}
    footer={<WorkflowDesignFooter loading step={step} onSave={noop} onMove={noop} onDelete={noop}/>}>
    {step && <WorkflowDesignFields loading flow={flow} step={step} members={[]} onStep={noop} onField={noop} onAddField={noop} onRemoveField={noop}/>}
  </WorkflowInspectorFrame>;
}
