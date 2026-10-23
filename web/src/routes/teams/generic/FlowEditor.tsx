import styles from "./FlowEditor.styles";
import { ArrowDown, Bot, CheckCircle2, Circle, Clock3, FileCheck2, Inbox, LoaderCircle, PauseCircle, TriangleAlert, UserRound } from "lucide-react";
import { VNativeButton, VSkeleton } from "../../../components/vui";
import { KIND_LABEL, memberName, type Flow, type Run, type StepKind, type WorkflowMember } from "./workflowModel";

type Props = { loading?: boolean; flow: Flow; selectedId: string; mode: "design" | "run"; run?: Run; members: WorkflowMember[]; onSelect: (id: string) => void; onAdd: () => void };
const kindIcons: Record<StepKind, typeof Bot> = { input: Inbox, agent: Bot, human: UserRound, output: FileCheck2, research: TriangleAlert, session: TriangleAlert };
const states = {
  configured: { label: "已配置", icon: CheckCircle2, color: "text-[var(--fg-tertiary)]" },
  draft: { label: "待配置", icon: Circle, color: "text-[var(--fg-tertiary)]" },
  pending: { label: "未开始", icon: Circle, color: "text-[var(--fg-tertiary)]" },
  completed: { label: "已完成", icon: CheckCircle2, color: "text-[var(--state-success)]" },
  running: { label: "执行中", icon: LoaderCircle, color: "text-[var(--accent-cool)]" },
  waiting: { label: "等待人工确认", icon: Clock3, color: "text-[var(--vui-status-warning-fg)]" },
  failed: { label: "执行失败", icon: TriangleAlert, color: "text-[var(--vui-status-danger-fg)]" },
  stopped: { label: "已停止", icon: PauseCircle, color: "text-[var(--fg-tertiary)]" },
};
function nodeState(index: number, mode: Props["mode"], instruction: string, run?: Run): keyof typeof states {
  if (mode === "design") return instruction.trim() ? "configured" : "draft";
  if (!run) return "pending";
  if (run.status === "completed" || index < run.current) return "completed";
  if (index > run.current) return "pending";
  return run.status;
}
export function FlowEditor({ loading, flow, selectedId, mode, run, members, onSelect }: Props) {
  const ownerName = (id: string) => memberName(id, members);
  return <div data-team-flow-editor aria-hidden={loading || undefined} className={styles.part1}>
    <ol className={styles.part2}>
      {flow.steps.map((step,index) => {
        const stateKey = nodeState(index,mode,step.instruction,run);
        const state = states[stateKey];
        const Icon = kindIcons[step.kind];
        const Status = state.icon;
        const selected = (selectedId || flow.steps[0]?.id) === step.id;
        return <li key={step.id} className={styles.part3}>
          {index < flow.steps.length - 1 && <span aria-hidden="true" className={styles.part4}><ArrowDown size={12} className={styles.part5}/></span>}
          <span className={"relative mt-4 flex h-7 w-7 shrink-0 items-center justify-center rounded-full border bg-[var(--vui-surface-chat)] font-mono text-vui-micro-11 " + (selected ? "border-[var(--accent-cool)] text-[var(--accent-cool)]" : "border-[var(--vui-border-subtle)] text-[var(--fg-tertiary)]")}>{String(index+1).padStart(2,"0")}</span>
          <VNativeButton aria-pressed={selected} aria-label={(index+1)+". "+step.label+"，"+ownerName(step.owner)+"，"+state.label} onClick={() => onSelect(step.id)} className={(loading ? styles.pendingNode + " " : "") + "relative flex min-w-0 flex-1 flex-col gap-0 rounded-xl border bg-[var(--vui-surface-chat)] px-4 py-3 text-left shadow-[0_2px_4px_#00000003] transition-colors " + (selected ? "border-[var(--accent-cool)] ring-2 ring-[var(--vui-status-info-bg)]" : "border-[var(--vui-border-subtle)] hover:border-[var(--fg-tertiary)]")}>
            {loading && <div className={styles.pendingOverlay}><VSkeleton className={styles.pendingTitle}/><VSkeleton className={styles.pendingInstruction}/><VSkeleton className={styles.pendingMeta}/></div>}
            <span className={styles.part6}><span className={"flex h-7 w-7 shrink-0 items-center justify-center rounded-lg " + (step.kind === "human" ? "bg-[var(--vui-status-warning-bg)] text-[var(--vui-status-warning-fg)]" : selected ? "bg-[var(--vui-status-info-bg)] text-[var(--accent-cool)]" : "bg-[var(--vui-surface-row)] text-[var(--fg-secondary)]")}><Icon size={15}/></span><span className={styles.part7} title={step.label}>{step.label || "未命名步骤"}</span><span className={styles.part8}>{KIND_LABEL[step.kind]}</span></span>
            <span className={styles.part9}>{step.instruction || "点击配置这一步的执行要求。"}</span>
            <span className={styles.part10}><span className={styles.part11}><UserRound size={11}/><span className={styles.ownerName} title={ownerName(step.owner)}>{ownerName(step.owner) || "未分配"}</span></span><span className={styles.statusLabel+" "+state.color}><Status size={11} className={stateKey === "running" ? "animate-spin motion-reduce:animate-none" : ""}/>{state.label}</span></span>
          </VNativeButton>
        </li>;
      })}
      <li className={styles.part12}><span className={styles.part13}><span className={styles.part14}/></span><span className={styles.part15}>{mode === "design" ? "交付完成后结束本次流程" : "运行记录保留在当前预览中"}</span></li>
    </ol>
  </div>;
}
