import styles from "./FlowEditor.styles";
import { useEffect, useId, useRef, useState } from "react";
import { Bot, CheckCircle2, Circle, Clock3, FileCheck2, Inbox, LoaderCircle, PauseCircle, Plus, TriangleAlert, UserRound } from "lucide-react";
import { VButton } from "../../../components/vui";
import { KIND_LABEL, memberName, type Flow, type Run, type StepKind, type WorkflowMember } from "./workflowModel";
type Props = {
    flow: Flow;
    selectedId: string;
    mode: "design" | "run";
    run?: Run;
    members: WorkflowMember[];
    onSelect: (id: string) => void;
    onAdd: () => void;
};
const NODE_HEIGHT = 184;
const COLUMN_GAP = 40;
const ROW_GAP = 44;
const INSET = 20;
const kindIcons: Record<StepKind, typeof Bot> = { input: Inbox, agent: Bot, human: UserRound, output: FileCheck2 };
const states = {
    configured: { label: "已配置", icon: CheckCircle2, color: styles.text1 },
    draft: { label: "待配置", icon: Circle, color: styles.text2 },
    pending: { label: "未开始", icon: Circle, color: styles.text2 },
    completed: { label: "已完成", icon: CheckCircle2, color: styles.text3 },
    running: { label: "执行中", icon: LoaderCircle, color: styles.text3 },
    waiting: { label: "等待人工确认", icon: Clock3, color: styles.text4 },
    failed: { label: "执行失败", icon: TriangleAlert, color: styles.text5 },
    stopped: { label: "已停止", icon: PauseCircle, color: styles.text6 },
};
function nodeState(index: number, mode: Props["mode"], instruction: string, run?: Run): keyof typeof states {
    if (mode === "design")
        return instruction.trim() ? "configured" : "draft";
    if (!run)
        return "pending";
    if (run.status === "completed" || index < run.current)
        return "completed";
    if (index > run.current)
        return "pending";
    return run.status;
}
export function FlowEditor({ flow, selectedId, mode, run, members, onSelect, onAdd }: Props) {
    const ownerName = (id: string) => memberName(id, members);
    const viewport = useRef<HTMLDivElement>(null);
    const [width, setWidth] = useState(0);
    const arrowId = `flow-arrow-${useId().replace(/:/g, "")}`;
    useEffect(() => {
        const element = viewport.current;
        if (!element)
            return;
        const observer = new ResizeObserver(entries => setWidth(entries[0]?.contentRect.width ?? 0));
        observer.observe(element);
        return () => observer.disconnect();
    }, []);
    const columns = width < 540 ? 1 : width < 900 ? 2 : 3;
    const cardWidth = Math.max(0, (width - INSET * 2 - COLUMN_GAP * (columns - 1)) / columns);
    const rows = Math.ceil(flow.steps.length / columns);
    const height = rows ? INSET * 2 + rows * NODE_HEIGHT + (rows - 1) * ROW_GAP : 0;
    // Alternate row direction so every connector joins consecutive steps at adjacent ports.
    const positions = flow.steps.map((_, index) => {
        const row = Math.floor(index / columns);
        const column = row % 2 ? columns - 1 - index % columns : index % columns;
        return { x: INSET + column * (cardWidth + COLUMN_GAP), y: INSET + row * (NODE_HEIGHT + ROW_GAP), row };
    });
    const selected = selectedId || flow.steps[0]?.id;
    return <div className={styles.column1} data-team-flow-editor="true">
    <div className={styles.row1}>
      <div ref={viewport} className={styles.control1}>
        {width > 0 && <div className={styles.control2} style={{ height }}>
          <svg className={styles.control3} width={width} height={height} aria-hidden="true">
            <defs><marker id={arrowId} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#8b9d91"/></marker></defs>
            {positions.slice(0, -1).map((from, index) => {
                const to = positions[index + 1];
                const sameRow = from.row === to.row;
                const forward = to.x > from.x;
                const x1 = sameRow ? from.x + (forward ? cardWidth : 0) : from.x + cardWidth / 2;
                const y1 = from.y + (sameRow ? NODE_HEIGHT / 2 : NODE_HEIGHT);
                const x2 = sameRow ? to.x + (forward ? 0 : cardWidth) : to.x + cardWidth / 2;
                const y2 = to.y + (sameRow ? NODE_HEIGHT / 2 : 0);
                return <path key={flow.steps[index].id} d={`M ${x1} ${y1} L ${x2} ${y2}`} fill="none" stroke="#8b9d91" strokeWidth="1.6" markerEnd={`url(#${arrowId})`}/>;
            })}
          </svg>
          {flow.steps.map((step, index) => {
                const stateKey = nodeState(index, mode, step.instruction, run);
                const state = states[stateKey];
                const KindIcon = kindIcons[step.kind];
                const StatusIcon = state.icon;
                const isSelected = selected === step.id;
                return <div key={step.id} className={styles.control4} style={{ left: positions[index].x, top: positions[index].y, width: cardWidth, height: NODE_HEIGHT }}>
              <VButton contentLayout="plain" onClick={() => onSelect(step.id)} aria-pressed={isSelected} aria-label={`${index + 1}. ${step.label}，${ownerName(step.owner)}，${state.label}`} className={[styles.column2, isSelected ? styles.control5 : styles.control6].filter(Boolean).join(" ")}>
                <span className={styles.row2}>
                  <span className={styles.caption1}><span className={styles.row3}><KindIcon size={16} aria-hidden="true"/></span><span className={styles.control7}>{KIND_LABEL[step.kind]}</span></span>
                  <span className={styles.caption2}>{String(index + 1).padStart(2, "0")}</span>
                </span>
                <span className={styles.heading1} title={step.label}>{step.label || "未命名步骤"}</span>
                <span className={styles.text7}>{step.instruction || "添加执行要求，告诉成员这一步需要完成什么。"}</span>
                <span className={styles.caption3}>
                  <span className={styles.row4}><UserRound size={12} className={styles.control8} aria-hidden="true"/><span className={styles.control7} title={ownerName(step.owner)}> {ownerName(step.owner) || "未分配"}</span></span>
                  <span className={[styles.row5, state.color].filter(Boolean).join(" ")}><StatusIcon size={12} className={stateKey === "running" ? styles.control9 : ""} aria-hidden="true"/>{state.label}</span>
                </span>
              </VButton>
            </div>;
            })}
        </div>}
      </div>
      <div className={styles.control10}>
        {flow.steps.length === 0 && <p className={styles.text8}>还没有步骤，从添加第一个步骤开始。</p>}
        {mode === "design" && <VButton icon={<Plus size={15}/>} onClick={onAdd} className={styles.surface1}>添加步骤</VButton>}
        <p className={styles.caption4}>{mode === "design" ? "按箭头顺序执行 · 点击步骤进行配置" : "点击步骤查看本次执行详情"}</p>
      </div>
    </div>
  </div>;
}
