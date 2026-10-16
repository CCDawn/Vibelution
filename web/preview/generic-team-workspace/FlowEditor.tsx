import { useEffect, useId, useRef, useState } from "react";
import { Bot, CheckCircle2, Circle, Clock3, FileCheck2, Inbox, LoaderCircle, PauseCircle, Plus, TriangleAlert, UserRound } from "lucide-react";
import { VButton } from "../../src/components/vui";
import { KIND_LABEL, ownerName, type Flow, type Run, type StepKind } from "./fixtures";

type Props = { flow: Flow; selectedId: string; mode: "design" | "run"; run?: Run; onSelect: (id: string) => void; onAdd: () => void };
const NODE_HEIGHT = 184;
const COLUMN_GAP = 40;
const ROW_GAP = 44;
const INSET = 20;
const kindIcons: Record<StepKind, typeof Bot> = { input: Inbox, agent: Bot, human: UserRound, output: FileCheck2 };
const states = {
  configured: { label: "已配置", icon: CheckCircle2, color: "text-[#65766f]" },
  draft: { label: "待配置", icon: Circle, color: "text-[#7d8581]" },
  pending: { label: "未开始", icon: Circle, color: "text-[#7d8581]" },
  completed: { label: "已完成", icon: CheckCircle2, color: "text-[#256c58]" },
  running: { label: "执行中", icon: LoaderCircle, color: "text-[#256c58]" },
  waiting: { label: "等待人工确认", icon: Clock3, color: "text-[#9b680f]" },
  failed: { label: "执行失败", icon: TriangleAlert, color: "text-[#b34436]" },
  stopped: { label: "已停止", icon: PauseCircle, color: "text-[#707772]" },
};

function nodeState(index: number, mode: Props["mode"], instruction: string, run?: Run): keyof typeof states {
  if (mode === "design") return instruction.trim() ? "configured" : "draft";
  if (!run) return "pending";
  if (run.status === "completed" || index < run.current) return "completed";
  if (index > run.current) return "pending";
  return run.status;
}

export function FlowEditor({ flow, selectedId, mode, run, onSelect, onAdd }: Props) {
  const viewport = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  const arrowId = `flow-arrow-${useId().replace(/:/g, "")}`;
  useEffect(() => {
    const element = viewport.current;
    if (!element) return;
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

  return <div className="flex h-full min-h-0 min-w-0 flex-1 flex-col bg-[#fafbf9] text-[#25382f]" data-preview-flow-editor="true">
    <div className="min-h-0 flex-1 overflow-auto bg-[radial-gradient(#dfe5df_1px,transparent_1px)] bg-[length:18px_18px]">
      <div ref={viewport} className="w-full min-w-0">
        {width > 0 && <div className="relative" style={{ height }}>
          <svg className="pointer-events-none absolute inset-0 overflow-visible" width={width} height={height} aria-hidden="true">
            <defs><marker id={arrowId} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#8b9d91" /></marker></defs>
            {positions.slice(0, -1).map((from, index) => {
              const to = positions[index + 1];
              const sameRow = from.row === to.row;
              const forward = to.x > from.x;
              const x1 = sameRow ? from.x + (forward ? cardWidth : 0) : from.x + cardWidth / 2;
              const y1 = from.y + (sameRow ? NODE_HEIGHT / 2 : NODE_HEIGHT);
              const x2 = sameRow ? to.x + (forward ? 0 : cardWidth) : to.x + cardWidth / 2;
              const y2 = to.y + (sameRow ? NODE_HEIGHT / 2 : 0);
              return <path key={flow.steps[index].id} d={`M ${x1} ${y1} L ${x2} ${y2}`} fill="none" stroke="#8b9d91" strokeWidth="1.6" markerEnd={`url(#${arrowId})`} />;
            })}
          </svg>
          {flow.steps.map((step, index) => {
            const stateKey = nodeState(index, mode, step.instruction, run);
            const state = states[stateKey];
            const KindIcon = kindIcons[step.kind];
            const StatusIcon = state.icon;
            const isSelected = selected === step.id;
            return <div key={step.id} className="absolute" style={{ left: positions[index].x, top: positions[index].y, width: cardWidth, height: NODE_HEIGHT }}>
              <VButton contentLayout="plain" onClick={() => onSelect(step.id)} aria-pressed={isSelected} aria-label={`${index + 1}. ${step.label}，${ownerName(step.owner)}，${state.label}`} className={`!flex !h-full !w-full !flex-col !items-stretch !justify-start !gap-0 !whitespace-normal !rounded-xl !border !bg-white !p-4 !text-left !font-normal !shadow-sm transition-shadow hover:!shadow-md focus-visible:!ring-[#256c58] ${isSelected ? "!border-[#256c58] !ring-2 !ring-[#256c58]/15" : "!border-[#dbe2db] hover:!border-[#91b4a3]"}`}>
                <span className="flex min-w-0 items-center justify-between gap-2">
                  <span className="flex min-w-0 items-center gap-2 text-xs text-[#5f7467]"><span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-[#edf4ee] text-[#256c58]"><KindIcon size={16} aria-hidden="true" /></span><span className="truncate">{KIND_LABEL[step.kind]}</span></span>
                  <span className="font-mono text-xs text-[#9aa59c]">{String(index + 1).padStart(2, "0")}</span>
                </span>
                <span className="mt-2 block truncate text-[15px] font-semibold leading-6 text-[#25382f]" title={step.label}>{step.label || "未命名步骤"}</span>
                <span className="mt-1 line-clamp-2 min-h-10 text-sm leading-5 text-[#6b776f]">{step.instruction || "添加执行要求，告诉成员这一步需要完成什么。"}</span>
                <span className="mt-auto flex min-w-0 items-center justify-between gap-2 border-t border-[#edf0eb] pt-2 text-xs">
                  <span className="flex min-w-0 items-center gap-1.5 text-[#637167]"><UserRound size={12} className="shrink-0" aria-hidden="true" /><span className="truncate" title={ownerName(step.owner)}> {ownerName(step.owner) || "未分配"}</span></span>
                  <span className={`flex shrink-0 items-center gap-1 ${state.color}`}><StatusIcon size={12} className={stateKey === "running" ? "animate-spin motion-reduce:animate-none" : ""} aria-hidden="true" />{state.label}</span>
                </span>
              </VButton>
            </div>;
          })}
        </div>}
      </div>
      <div className="px-5 pb-6">
        {flow.steps.length === 0 && <p className="py-5 text-sm text-[#6b776f]">还没有步骤，从添加第一个步骤开始。</p>}
        {mode === "design" && <VButton icon={<Plus size={15} />} onClick={onAdd} className="!h-10 !border-dashed !border-[#a9c3b3] !bg-white/90 !px-4 !text-sm !text-[#256c58] hover:!bg-[#edf4ee]">添加步骤</VButton>}
        <p className="mt-4 text-xs text-[#849087]">{mode === "design" ? "按箭头顺序执行 · 点击步骤进行配置" : "点击步骤查看本次执行详情"}</p>
      </div>
    </div>
  </div>;
}
