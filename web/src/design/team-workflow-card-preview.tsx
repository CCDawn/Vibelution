/**
 * Isolated research-workflow card preview.
 * Open: /team-workflow-card-preview.html
 * Design acceptance only — does not change VWorkflowCanvas or TeamsRoute.
 */
import { StrictMode, useMemo, useState, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import {
  AlertTriangle,
  Bot,
  Check,
  Circle,
  GitBranch,
  Loader2,
  Package,
  Play,
  User,
  X,
} from "lucide-react";

import { VButton, VuiProvider } from "../components/vui";
import "./base.css";
import "./tokens.css";
import "./vui-native-controls.css";
import "./vui-provider-theme.css";
import "./team-workflow-card-preview.css";
import { teamWorkflowCardPreviewStyles as styles } from "./team-workflow-card-preview.styles";

type SceneId = "pending" | "running" | "waiting_human" | "succeeded" | "failed" | "selected";
type KindId = "start" | "agent" | "human" | "system" | "decision";
type StatusId = "pending" | "running" | "waiting_human" | "succeeded" | "failed";

type FlowNode = {
  id: string;
  title: string;
  kind: KindId;
  role: string;
  agent: string | null;
};

const SCENE_COPY: Record<SceneId, string> = {
  pending: "待运行",
  running: "运行中",
  waiting_human: "等待人工",
  succeeded: "已完成",
  failed: "失败",
  selected: "选中",
};

const KIND_LABEL: Record<KindId, string> = {
  start: "起点",
  agent: "Agent",
  human: "人工",
  system: "系统",
  decision: "决策",
};

const STATUS_LABEL: Record<StatusId, string> = {
  pending: "待运行",
  running: "运行中",
  waiting_human: "等待人工",
  succeeded: "已完成",
  failed: "失败",
};

const KNOWLEDGE_NODES: FlowNode[] = [
  { id: "start", title: "资料寻找", kind: "start", role: "资料搜集", agent: null },
  { id: "find", title: "资料寻找", kind: "agent", role: "资料搜集", agent: "白望舒" },
  { id: "extract", title: "资料提炼", kind: "agent", role: "证据提炼", agent: "顾言初" },
  { id: "ingest", title: "知识入库", kind: "human", role: "科研负责人", agent: null },
];

const EXPERIMENT_NODES: FlowNode[] = [
  { id: "hypothesis", title: "提出假设", kind: "agent", role: "实验规划", agent: "林知序" },
  { id: "protocol", title: "冻结协议", kind: "agent", role: "实验台账", agent: "沈观止" },
  { id: "gate", title: "人工确认", kind: "human", role: "科研负责人", agent: null },
];

function sceneStatus(scene: SceneId, node: FlowNode, index: number): StatusId {
  if (scene === "selected") return "pending";
  if (scene === "waiting_human") {
    return node.kind === "human" ? "waiting_human" : index === 0 ? "succeeded" : "pending";
  }
  if (scene === "running") {
    if (index === 0) return "succeeded";
    if (index === 1) return "running";
    return "pending";
  }
  if (scene === "succeeded") return "succeeded";
  if (scene === "failed") return index === 1 ? "failed" : index === 0 ? "succeeded" : "pending";
  return "pending";
}

function KindIcon({ kind, size = 16 }: { kind: KindId; size?: number }) {
  if (kind === "start") return <Play size={size} aria-hidden />;
  if (kind === "human") return <User size={size} aria-hidden />;
  if (kind === "system") return <Package size={size} aria-hidden />;
  if (kind === "decision") return <GitBranch size={size} aria-hidden />;
  return <Bot size={size} aria-hidden />;
}

function StatusGlyph({ status, size = 12 }: { status: StatusId; size?: number }) {
  if (status === "running") return <Loader2 size={size} aria-hidden />;
  if (status === "succeeded") return <Check size={size} aria-hidden />;
  if (status === "failed") return <X size={size} aria-hidden />;
  if (status === "waiting_human") return <AlertTriangle size={size} aria-hidden />;
  return <Circle size={size} aria-hidden />;
}

function currentMeta(node: FlowNode): string {
  if (node.kind === "human") return "人工确认";
  if (node.agent) return "Agent 已绑定";
  return "待运行";
}

function currentFootRight(node: FlowNode): string {
  if (node.kind === "start") return "起点";
  if (node.kind === "human") return "人工";
  return node.agent ? "已绑定" : "未绑定";
}

function proposedSub(node: FlowNode): string {
  if (node.agent) return `${node.role} · ${node.agent}`;
  if (node.kind === "human") return `${node.role} · 待确认`;
  if (node.kind === "start") return `${node.role} · 流程入口`;
  return `${node.role} · 未绑定`;
}

function CurrentCard({
  node,
  status,
  selected,
}: {
  node: FlowNode;
  status: StatusId;
  selected?: boolean;
}) {
  return (
    <div
      className="twc-current"
      data-kind={node.kind}
      data-status={status}
      data-selected={selected ? "true" : "false"}
      data-testid={`current-${node.id}`}
    >
      <div className="twc-current-top">
        <div className="twc-current-id">
          <span className="twc-current-icon">
            <KindIcon kind={node.kind} />
          </span>
          <span className="twc-current-title">{node.title}</span>
        </div>
        <span className="twc-current-kind">{KIND_LABEL[node.kind]}</span>
      </div>
      <div className="twc-current-mid">
        <span className="twc-current-badge">
          <StatusGlyph status={status} />
          {STATUS_LABEL[status]}
        </span>
        <span className="twc-current-meta">{currentMeta(node)}</span>
      </div>
      <div className="twc-current-foot">
        <span>{node.role}</span>
        <span>{currentFootRight(node)}</span>
      </div>
    </div>
  );
}

function ProposedCard({
  node,
  status,
  selected,
}: {
  node: FlowNode;
  status: StatusId;
  selected?: boolean;
}) {
  return (
    <div
      className="twc-proposed"
      data-kind={node.kind}
      data-status={status}
      data-selected={selected ? "true" : "false"}
      data-testid={`proposed-${node.id}`}
    >
      <span className="twc-port twc-port-in" aria-hidden />
      <span className="twc-port twc-port-out" aria-hidden />
      <span className="twc-proposed-icon">
        <KindIcon kind={node.kind} size={22} />
        <span className="twc-proposed-mark" aria-label={STATUS_LABEL[status]}>
          <StatusGlyph status={status} size={10} />
        </span>
      </span>
      <span className="twc-proposed-copy">
        <span className="twc-proposed-title">{node.title}</span>
        <span className="twc-proposed-sub">{proposedSub(node)}</span>
      </span>
    </div>
  );
}

function FlowStrip({
  nodes,
  scene,
  render,
}: {
  nodes: FlowNode[];
  scene: SceneId;
  render: (node: FlowNode, status: StatusId, selected: boolean) => ReactNode;
}) {
  return (
    <div className={styles.flow}>
      {nodes.map((node, index) => {
        const status = sceneStatus(scene, node, index);
        const selected = scene === "selected" && index === 1;
        return (
          <span key={node.id} className={styles.step}>
            {index > 0 ? <span className={styles.arrow} aria-hidden /> : null}
            {render(node, status, selected)}
          </span>
        );
      })}
    </div>
  );
}

function StageBand({
  index,
  title,
  chip,
  children,
}: {
  index: string;
  title: string;
  chip: string;
  children: ReactNode;
}) {
  return (
    <section className={styles.stage} aria-label={title}>
      <div className={styles.stageHead}>
        <span className={styles.stageIndex}>{index}</span>
        <span className={styles.stageTitle}>{title}</span>
        <span className={styles.stageChip}>{chip}</span>
      </div>
      {children}
    </section>
  );
}

function readPreviewSearch(): SceneId {
  const scene = new URLSearchParams(window.location.search).get("scene");
  return scene && scene in SCENE_COPY ? (scene as SceneId) : "running";
}

export function TeamWorkflowCardPreviewApp() {
  const [scene, setScene] = useState<SceneId>(readPreviewSearch);
  const gallery = useMemo<FlowNode[]>(
    () => [
      { id: "g-start", title: "流程起点", kind: "start", role: "资料搜集", agent: null },
      { id: "g-agent", title: "资料寻找", kind: "agent", role: "资料搜集", agent: "白望舒" },
      { id: "g-human", title: "知识入库", kind: "human", role: "科研负责人", agent: null },
      { id: "g-system", title: "受控执行", kind: "system", role: "正式运行", agent: null },
      { id: "g-decision", title: "是否晋级", kind: "decision", role: "迭代规划", agent: "林知序" },
    ],
    [],
  );

  return (
    <main className={styles.page}>
      <header className={styles.header}>
        <p className={styles.eyebrow}>科研流程画布</p>
        <h1>上一版只是加大字号，这一版换成模块卡</h1>
        <p className={styles.subtitle}>
          现网仍是三行挤卡、横排蛇形。建议侧改成 n8n 式模块：实心类型色块、标题加一行说明、状态叠在图标角上；流程改竖排，不再跟左边长得一样。
        </p>
        <div className={styles.scenes} role="tablist" aria-label="运行状态">
          {(Object.keys(SCENE_COPY) as SceneId[]).map((id) => (
            <VButton
              key={id}
              type="button"
              density="compact"
              variant={scene === id ? "primary" : "secondary"}
              aria-pressed={scene === id}
              onClick={() => setScene(id)}
            >
              {SCENE_COPY[id]}
            </VButton>
          ))}
        </div>
      </header>

      <div className={styles.compare}>
        <section className={styles.column} data-side="current">
          <div className={styles.columnLabel}>现在 · 横排挤卡 · 244×102</div>
          <StageBand index="1" title="知识搜集" chip="进行中">
            <FlowStrip
              nodes={KNOWLEDGE_NODES}
              scene={scene}
              render={(node, status, selected) => (
                <CurrentCard node={node} status={status} selected={selected} />
              )}
            />
          </StageBand>
          <StageBand index="2" title="实验设计" chip="等待前置">
            <FlowStrip
              nodes={EXPERIMENT_NODES}
              scene={scene}
              render={(node, status, selected) => (
                <CurrentCard node={node} status={status} selected={selected} />
              )}
            />
          </StageBand>
        </section>
        <section className={styles.column} data-side="proposed">
          <div className={styles.columnLabel}>建议 · 竖排模块卡 · 实心色块</div>
          <StageBand index="1" title="知识搜集" chip="进行中">
            <FlowStrip
              nodes={KNOWLEDGE_NODES}
              scene={scene}
              render={(node, status, selected) => (
                <ProposedCard node={node} status={status} selected={selected} />
              )}
            />
          </StageBand>
          <StageBand index="2" title="实验设计" chip="等待前置">
            <FlowStrip
              nodes={EXPERIMENT_NODES}
              scene={scene}
              render={(node, status, selected) => (
                <ProposedCard node={node} status={status} selected={selected} />
              )}
            />
          </StageBand>
        </section>
      </div>

      <section className={styles.gallery} aria-label="类型识别">
        <div className={styles.galleryLabel}>建议卡 · 类型只靠实心色块，状态只靠图标角标</div>
        <div className={styles.flow}>
          {gallery.map((node) => (
            <ProposedCard key={node.id} node={node} status="pending" />
          ))}
        </div>
      </section>

      <aside className={styles.borrow} aria-label="借鉴来源">
        <div className={styles.borrowItem}>
          <strong>Dify 节点</strong>
          <span>彩色实心类型图标做第一扫描目标；运行态走描边和角标，不给整张卡染色。</span>
        </div>
        <div className={styles.borrowItem}>
          <strong>n8n 节点</strong>
          <span>标题下一行副标题就够：角色 · 绑定人。状态叠在图标角上，不再做第三行脚注。</span>
        </div>
        <div className={styles.borrowItem}>
          <strong>本项目保留</strong>
          <span>阶段带、VUI token、Agent/人工/系统/决策语义。不引入第二套设计系统，也不改 Inspector。</span>
        </div>
      </aside>

      <p className={styles.note}>
        预览只用假数据，没有接运行接口，也没有改正式画布。批准后才会动
        WorkflowNodeChrome / 蛇形节点尺寸。组织画布上的角色卡不是这一页的范围。
      </p>
    </main>
  );
}

const previewRoot = document.getElementById("root");
if (previewRoot) {
  createRoot(previewRoot).render(
    <StrictMode>
      <VuiProvider>
        <TeamWorkflowCardPreviewApp />
      </VuiProvider>
    </StrictMode>,
  );
}
