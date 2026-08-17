import { StrictMode, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import { ChevronDown, MessageSquare, Settings2, Users } from "lucide-react";

import {
  VButton,
  VIconButton,
  VNativeButton,
  VNativeInput,
  VPopover,
  VStatusChip,
  VSurface,
  VTooltip,
  VuiProvider,
} from "../components/vui";
import "./base.css";
import "./tokens.css";
import "./vui-native-controls.css";
import "./vui-provider-theme.css";
import "./team-node-inspector-preview.css";
import { teamNodeInspectorPreviewStyles as styles } from "./team-node-inspector-preview.styles";

type SceneId = "bound" | "unbound" | "tight" | "running";
type ProviderId = "qwen" | "deepseek" | "anthropic";

type ModelOption = {
  id: string;
  label: string;
  provider: ProviderId;
  providerLabel: string;
  hint: string;
};

type AgentOption = {
  id: string;
  name: string;
  initial: string;
  modelId: string;
};

const MODELS: ModelOption[] = [
  { id: "qwen-plus", label: "qwen-plus", provider: "qwen", providerLabel: "通义", hint: "快 · 默认" },
  { id: "deepseek-v3", label: "deepseek-v3", provider: "deepseek", providerLabel: "DeepSeek", hint: "均衡" },
  { id: "claude-sonnet-4", label: "claude-sonnet-4", provider: "anthropic", providerLabel: "Anthropic", hint: "强推理" },
];

const AGENTS: AgentOption[] = [
  { id: "agent-ingestor", name: "资料入库", initial: "资", modelId: "qwen-plus" },
  { id: "agent-finder", name: "白望舒", initial: "白", modelId: "deepseek-v3" },
  { id: "agent-extractor", name: "顾言初", initial: "顾", modelId: "claude-sonnet-4" },
];

const SCENE_COPY: Record<SceneId, string> = {
  bound: "已绑定",
  unbound: "未指定",
  tight: "预算将尽",
  running: "运行中",
};

function modelOf(id: string): ModelOption {
  return MODELS.find((item) => item.id === id) ?? MODELS[0];
}

function CurrentInspector() {
  return (
    <VSurface tone="panel" className={styles.inspector} data-testid="inspector-current">
      <header className={styles.currentHeader}>
        <h3 className={styles.currentTitle}>知识入库</h3>
      </header>
      <dl className={styles.currentGrid}>
        <dt>执行者</dt>
        <dd>agent</dd>
        <dt>角色</dt>
        <dd>source_ingestor</dd>
      </dl>
      <section className={styles.currentCard} aria-label="Agent 配置">
        <div className={styles.currentCardHead}>Agent 配置</div>
        <div className={styles.currentFields}>
          <span>
            <small>职责</small>
            <strong>知识入库</strong>
          </span>
          <span>
            <small>Agent</small>
            <strong>资料入库</strong>
          </span>
        </div>
        <div className={styles.currentFooter}>
          <span>已绑定 · 团队/工作流默认</span>
          <VButton type="button" variant="secondary" density="compact">Agent 配置</VButton>
        </div>
      </section>
    </VSurface>
  );
}

function BudgetMeter(props: {
  label: string;
  percent: number;
  detail: string;
}) {
  const warn = props.percent >= 80;
  return (
    <VTooltip content={props.detail}>
      <div className={`${styles.meter} ${warn ? styles.meterWarn : ""}`}>
        <div className={styles.meterHead}>
          <span>{props.label}</span>
          <span>{props.percent}%</span>
        </div>
        <div className={styles.meterTrack} aria-hidden="true">
          <div
            className={styles.meterFill}
            style={{ ["--tni-fill" as string]: `${Math.max(4, Math.min(100, props.percent))}%` }}
          />
        </div>
      </div>
    </VTooltip>
  );
}

function ProposedInspector(props: {
  scene: SceneId;
  agentId: string;
  modelId: string;
  onAgentChange: (agentId: string) => void;
  onModelChange: (modelId: string) => void;
}) {
  const [pickerOpen, setPickerOpen] = useState(false);
  const [query, setQuery] = useState("");
  const unbound = props.scene === "unbound";
  const agent = unbound ? null : AGENTS.find((item) => item.id === props.agentId) ?? AGENTS[0];
  const model = unbound ? null : modelOf(props.modelId);
  const tokens = props.scene === "tight" ? 88 : props.scene === "running" ? 42 : 8;
  const tools = props.scene === "tight" ? 81 : props.scene === "running" ? 18 : 4;
  const time = props.scene === "tight" ? 84 : props.scene === "running" ? 11 : 2;
  const statusTone = props.scene === "running" ? "accent" : props.scene === "tight" ? "warning" : unbound ? "neutral" : "success";
  const statusLabel = props.scene === "running" ? "运行中" : props.scene === "tight" ? "将尽" : unbound ? "待指定" : "待运行";

  const filteredModels = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return MODELS;
    return MODELS.filter((item) => `${item.label} ${item.providerLabel} ${item.hint}`.toLowerCase().includes(needle));
  }, [query]);

  return (
    <VSurface tone="panel" className={styles.inspector} data-testid="inspector-proposed">
      <header className={styles.proposedHead}>
        <div className={styles.stage}>知识搜集</div>
        <div className={styles.titleRow}>
          <h3 className={styles.title}>知识入库</h3>
          <VStatusChip tone={statusTone}>{statusLabel}</VStatusChip>
        </div>
      </header>

      <div className={styles.identity}>
        <span className={agent ? styles.avatar : styles.avatarEmpty} aria-hidden="true">
          {agent?.initial ?? "?"}
        </span>
        <div className={styles.identityCopy}>
          <strong className={styles.name}>{agent?.name ?? "未指定 Agent"}</strong>
        </div>
        <VIconButton
          label="更换 Agent"
          icon={<Users size={15} />}
          variant="ghost"
          isDisabled={unbound}
          onClick={() => {
            const currentIndex = AGENTS.findIndex((item) => item.id === props.agentId);
            const next = AGENTS[(currentIndex + 1) % AGENTS.length];
            props.onAgentChange(next.id);
            props.onModelChange(next.modelId);
          }}
        />
      </div>

      <VPopover
        open={pickerOpen}
        onOpenChange={setPickerOpen}
        align="start"
        contentClassName={styles.picker}
        trigger={(
          <VNativeButton
            className={styles.modelTrigger}
            data-provider={model?.provider ?? "qwen"}
            data-empty={unbound ? "true" : "false"}
            data-testid="model-trigger"
            disabled={unbound}
            aria-label={unbound ? "先指定 Agent 再换模型" : `当前模型 ${model?.label ?? ""}`}
          >
            <span className={styles.modelRail} aria-hidden="true" />
            <span className={styles.modelBody}>
              <span className={styles.modelKicker}>模型</span>
              <span className={styles.modelName}>{unbound ? "—" : model?.label}</span>
              <span className={styles.modelMeta}>
                {unbound ? "指定 Agent 后可切换" : `${model?.providerLabel} · ${model?.hint}`}
              </span>
            </span>
            <ChevronDown size={16} aria-hidden="true" />
          </VNativeButton>
        )}
      >
        <div className={styles.pickerSearch}>
          <VNativeInput
            aria-label="搜索模型"
            placeholder="搜索模型"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </div>
        <div className={styles.pickerList} role="listbox" aria-label="模型">
          {filteredModels.map((item) => {
            const active = item.id === props.modelId;
            return (
              <VNativeButton
                key={item.id}
                className={`${styles.pickerItem} ${active ? styles.pickerItemActive : ""}`}
                data-provider={item.provider}
                aria-selected={active}
                onClick={() => {
                  props.onModelChange(item.id);
                  setPickerOpen(false);
                }}
              >
                <span className={styles.modelRail} aria-hidden="true" />
                <span className={styles.pickerItemCopy}>
                  <strong className={styles.modelName}>{item.label}</strong>
                  <span className={styles.modelMeta}>{item.providerLabel} · {item.hint}</span>
                </span>
              </VNativeButton>
            );
          })}
        </div>
      </VPopover>

      <section className={styles.budget} aria-label="节点预算">
        <BudgetMeter label="Tokens" percent={tokens} detail="本阶段 token 已用 / 上限" />
        <BudgetMeter label="工具" percent={tools} detail="工具调用已用 / 上限" />
        <BudgetMeter label="时间" percent={time} detail="墙钟时间已用 / 上限" />
      </section>

      <div className={styles.actions}>
        <VButton type="button" variant="primary" isDisabled={unbound}>
          {props.scene === "running" ? "继续" : "启动"}
        </VButton>
        <VIconButton label="打开会话" icon={<MessageSquare size={15} />} variant="ghost" isDisabled={unbound} />
        <VIconButton label="源配置" icon={<Settings2 size={15} />} variant="ghost" isDisabled={unbound} />
      </div>
    </VSurface>
  );
}

function readPreviewSearch(): SceneId {
  const scene = new URLSearchParams(window.location.search).get("scene");
  return scene === "unbound" || scene === "tight" || scene === "running" || scene === "bound"
    ? scene
    : "bound";
}

export function TeamNodeInspectorPreviewApp() {
  const [scene, setScene] = useState<SceneId>(readPreviewSearch);

  const [agentId, setAgentId] = useState(AGENTS[0].id);
  const [modelId, setModelId] = useState(AGENTS[0].modelId);

  return (
    <main className={styles.page}>
      <header className={styles.header}>
        <p className={styles.eyebrow}>流程节点右侧配置</p>
        <h1>先看模型，再看预算</h1>
        <p className={styles.subtitle}>
          去掉执行者 / 角色 / 职责说明。身份只留头像和名字；最大块是可点的模型卡；预算用三条进度条，数字默认藏在悬停里。
        </p>
        <div className={styles.scenes} role="tablist" aria-label="状态">
          {(Object.keys(SCENE_COPY) as SceneId[]).map((id) => (
            <VButton
              key={id}
              type="button"
              density="compact"
              variant={scene === id ? "primary" : "secondary"}
              aria-pressed={scene === id}
              onClick={() => {
                setScene(id);
                if (id === "unbound") return;
                if (id === "bound") {
                  setAgentId(AGENTS[0].id);
                  setModelId(AGENTS[0].modelId);
                }
              }}
            >
              {SCENE_COPY[id]}
            </VButton>
          ))}
        </div>
      </header>

      <div className={styles.layout}>
        <section className={styles.column}>
          <div className={styles.columnLabel}>现在</div>
          <CurrentInspector />
        </section>
        <section className={styles.column}>
          <div className={styles.columnLabel}>建议</div>
          <ProposedInspector
            scene={scene}
            agentId={agentId}
            modelId={modelId}
            onAgentChange={setAgentId}
            onModelChange={setModelId}
          />
        </section>
      </div>
      <p className={styles.note}>
        预览不写正式接口。换模型拟写入该 Agent 的对话槽，不是节点级覆盖；预算条对应阶段安全上限已用比例。
      </p>
    </main>
  );
}

const previewRoot = document.getElementById("root");
if (previewRoot) {
  createRoot(previewRoot).render(
    <StrictMode>
      <VuiProvider>
        <TeamNodeInspectorPreviewApp />
      </VuiProvider>
    </StrictMode>,
  );
}
