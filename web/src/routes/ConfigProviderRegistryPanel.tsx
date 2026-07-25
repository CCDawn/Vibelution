import { AlertTriangle, Database, Image as ImageIcon, Pencil, RefreshCw, Route, Save, Trash2, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { WORKBENCH_LAYOUT_IDS } from "../components/layout/workbenchLayoutIds";
import { fetchJson } from "../api/client";
import {
  VActionGroup,
  VButton,
  VCheckbox,
  VDenseTable,
  VEntityList,
  VInput,
  VPanelHeader,
  VSection,
  VSplitWorkspace,
  VStateSurface,
  VStatusChip,
  VSurface,
  type VStatusTone,
} from "../components/vui";
import type {
  ConfigCapabilityObservation,
  ConfigCatalogModel,
  ConfigLlmTestResult,
  ConfigProviderMergePreview,
  ConfigProviderMergeResult,
} from "../api/types";
import {
  buildProviderSetupChecklist,
  canTestProviderModel,
  defaultProviderModelFilter,
  deriveProviderMergeCandidate,
  deriveProviderModelActionState,
  filterProviderModels,
  filterReadyProviderAssets,
  partitionReadyProviderAssets,
  pinnableProviderModels,
  sortProviderRegistryRows,
  summarizeProviderModels,
  type ProviderModelFilter,
  type ProviderRegistryRow,
} from "./configProviderLogic";
import styles from "./ConfigProviderRegistryPanel.styles";

export type ConfigProviderRegistryTab = "connection" | "models" | "protocols" | "diagnostics";

export type ProviderActionKind = "discover" | "credential" | "route" | "pin";

export type ProviderActionFeedback = {
  kind: ProviderActionKind;
  providerId: string;
  phase: "busy" | "success" | "error";
  message: string;
} | null;

export type ConfigProviderRegistryPanelProps = {
  rows: ProviderRegistryRow[];
  selectedProviderId: string;
  selectedTab: ConfigProviderRegistryTab;
  disabled: boolean;
  activeCredentialProviderId: string;
  credentialValue: string;
  activeRouteProviderId: string;
  imageCapabilityBusy: boolean;
  actionFeedback: ProviderActionFeedback;
  liveReferenceCountByModelRef: Record<string, number>;
  /** Draft has pending external save (pin / key / window / etc.). */
  hasPendingApply?: boolean;
  canSaveConfig?: boolean;
  saveBusy?: boolean;
  onSaveExternal?: () => void;
  onSelectProvider: (providerId: string) => void;
  onSelectTab: (tab: ConfigProviderRegistryTab) => void;
  onDiscover: (providerId: string) => void;
  onEditCredential: (providerId: string) => void;
  onCredentialValueChange: (value: string) => void;
  onCancelCredential: () => void;
  onSaveCredential: (providerId: string) => void;
  onSaveContextWindow: (providerId: string, contextWindow: number | null) => void;
  onEditRoute: (providerId: string) => void;
  onPin: (providerId: string, models: ConfigCatalogModel[]) => void;
  onUnpin: (modelRef: string) => void;
  onTestModel: (modelRef: string) => void;
  onProbeImageInput: (modelRef: string) => void;
  onDeleteProvider: (providerId: string) => void;
};

const TABS: Array<{ id: ConfigProviderRegistryTab; label: string }> = [
  { id: "connection", label: "连接" },
  { id: "models", label: "模型库 · 固定" },
  { id: "protocols", label: "协议与能力" },
  { id: "diagnostics", label: "诊断" },
];

const MODEL_FILTERS: Array<{
  id: ProviderModelFilter;
  label: string;
  countKey: "total" | "pinned" | "discovered" | "unavailable";
}> = [
  { id: "all", label: "全部", countKey: "total" },
  { id: "pinned", label: "已固定", countKey: "pinned" },
  { id: "discovered", label: "已发现", countKey: "discovered" },
  { id: "unavailable", label: "不可用", countKey: "unavailable" },
];

function statusTone(status: string): VStatusTone {
  if (status === "reachable") return "success";
  if (status === "stale" || status === "not_discovered" || status === "configured") return "warning";
  if (["auth_failed", "discovery_failed", "protocol_mismatch", "blocked"].includes(status)) return "danger";
  return "neutral";
}

function ProviderAssetRow({
  row,
  selected,
  inspecting,
  disabled,
  onSelect,
  onEdit,
}: {
  row: ProviderRegistryRow;
  selected: boolean;
  inspecting: boolean;
  disabled: boolean;
  onSelect: () => void;
  onEdit: () => void;
}) {
  return (
    <div
      className={styles.providerRow}
      data-active={selected ? "true" : "false"}
      data-inspecting={inspecting ? "true" : "false"}
      data-provider-status={row.status}
    >
      <VButton
        className={styles.providerButton}
        contentLayout="plain"
        variant={selected ? "primary" : "ghost"}
        title={`${row.label || row.providerId}\n${row.providerId}`}
        onPress={onSelect}
      >
        <span className={styles.providerIdentity}>
          <strong className={styles.providerLabel}>{row.label || row.providerId}</strong>
          <small className={styles.providerMeta}>
            {row.providerId}
            {row.pinnedCount > 0 ? ` · 已固定 ${row.pinnedCount}` : ""}
          </small>
        </span>
        <span className={styles.providerStatusRow}>
          <VStatusChip tone={statusTone(row.status)} data-provider-status={row.status}>{row.status}</VStatusChip>
        </span>
      </VButton>
      <VButton
        className={styles.providerEditButton}
        density="compact"
        variant={inspecting ? "primary" : "secondary"}
        icon={<Pencil size={14} />}
        data-provider-action="edit-asset"
        aria-label={`编辑 ${row.label || row.providerId}`}
        title={`编辑配置：${row.label || row.providerId}`}
        isDisabled={disabled}
        onPress={onEdit}
      >
        编辑
      </VButton>
    </div>
  );
}

function discoveryErrorLabel(errorType: string): string {
  switch (errorType) {
    case "timeout": return "请求超时";
    case "network": return "网络不可达";
    case "credential_missing": return "未配置凭据";
    case "credential_rejected":
    case "auth_failed": return "认证失败";
    case "endpoint_invalid": return "服务地址无效";
    case "protocol_mismatch": return "协议不兼容";
    case "invalid_response": return "返回格式不兼容";
    case "rate_limited": return "上游限流";
    case "upstream_rejected": return "上游拒绝请求";
    case "service_unavailable":
    case "upstream_unavailable":
    case "discovery_unavailable": return "上游暂不可用";
    case "blocked": return "访问被阻止";
    case "other": return "发现失败";
    default: return errorType || "无";
  }
}

function capabilityTone(observation: ConfigCapabilityObservation): VStatusTone {
  if (observation.value === "supported") return "success";
  if (observation.value === "unsupported") return "danger";
  return "warning";
}

function CapabilityList({ model }: { model: ConfigCatalogModel }) {
  const capabilities = Object.entries(model.capabilities);
  const reasoningValues = model.reasoningEffortValues ?? [];
  const reasoningSource = String(model.reasoningCapabilitySource || "");
  const isPinned = model.availability === "pinned" || model.availability === "missing_remote";
  const reasoningRows: Array<{ key: string; label: string; detail: string; tone: VStatusTone }> = [];
  // Only surface reasoning contract guidance for pinned models — never spam full discovery dumps.
  if (reasoningValues.length > 0) {
    const isOperator = reasoningSource === "operator_override" || model.reasoningVerificationStatus === "declared";
    reasoningRows.push({
      key: "reasoning_effort",
      label: `思考深度: ${reasoningValues.join("/")}`,
      detail: isOperator
        ? `协议已声明 · 默认 ${model.defaultReasoningEffort || "-"} · adapter ${model.reasoningAdapter || "none"}`
        : `已验证 · adapter ${model.reasoningAdapter || "none"}`,
      tone: "success",
    });
  } else if (isPinned) {
    reasoningRows.push({
      key: "reasoning_effort_missing",
      label: "思考深度: 未配置",
      detail: "固定后可写 pin defaults.reasoning_effort_values，或对 Responses 模型点「验证推理 low/high」",
      tone: "warning",
    });
  }
  if (!capabilities.length && !reasoningRows.length) {
    return <span className={styles.capabilityUnknown}>{isPinned ? "能力未观测" : "—"}</span>;
  }
  return (
    <div className={styles.capabilityList}>
      {reasoningRows.map((row) => (
        <span key={row.key} className={styles.providerIdentity} data-capability="reasoning_effort">
          <VStatusChip tone={row.tone}>{row.label}</VStatusChip>
          <small className={styles.muted} title={row.detail}>{row.detail}</small>
        </span>
      ))}
      {capabilities.map(([name, observation]) => (
        <span key={name} className={styles.providerIdentity}>
          <VStatusChip tone={capabilityTone(observation)}>
            {name}: {observation.value === "unknown" ? "unknown（未知）" : observation.value === "unsupported" ? "unsupported（不支持）" : "supported"}
          </VStatusChip>
          <small className={styles.muted}>
            {observation.source} · {observation.confidence || "confidence unknown"} · {observation.checked_at || "未记录时间"}
          </small>
        </span>
      ))}
    </div>
  );
}

function ProviderSetupChecklist({ provider }: { provider: ProviderRegistryRow }) {
  const items = buildProviderSetupChecklist(provider);
  const next = items.find((item) => !item.done);
  return (
    <div className={styles.setupChecklist} data-provider-checklist="true" aria-label="配置进度">
      <div className={styles.setupChecklistItems}>
        {items.map((item) => (
          <span
            key={item.id}
            className={styles.setupChecklistItem}
            data-done={item.done ? "true" : "false"}
            data-optional={item.optional ? "true" : "false"}
          >
            <VStatusChip tone={item.done ? "success" : item.optional ? "neutral" : "warning"}>
              {item.done ? "完成" : item.optional ? "可选" : "待办"}
            </VStatusChip>
            <small className={styles.muted}>{item.label}</small>
          </span>
        ))}
      </div>
      {next ? (
        <p className={styles.setupChecklistNext} role="status">
          下一步：{next.label}
          {next.id === "pin" ? "（在下方「已固定 / 已发现」中固定对话模型）" : ""}
          {next.id === "credential" ? "（点「设置 API Key」）" : ""}
          {next.id === "connection" ? "（点「发现」或检查路由）" : ""}
        </p>
      ) : (
        <p className={styles.setupChecklistNext} role="status">
          本 Provider 基础配置已完成。固定的模型可在 Agent 中选用。
        </p>
      )}
    </div>
  );
}

function ConnectionTab({
  provider,
  contextWindowDraft,
  credentialActive,
  credentialValue,
  disabled,
  onContextWindowDraftChange,
  onSaveContextWindow,
  onEditCredential,
  onCredentialValueChange,
  onCancelCredential,
  onSaveCredential,
}: {
  provider: ProviderRegistryRow;
  contextWindowDraft: string;
  credentialActive: boolean;
  credentialValue: string;
  disabled: boolean;
  onContextWindowDraftChange: (value: string) => void;
  onSaveContextWindow: () => void;
  onEditCredential: () => void;
  onCredentialValueChange: (value: string) => void;
  onCancelCredential: () => void;
  onSaveCredential: () => void;
}) {
  const needsKey = provider.credentialState !== "not_required";
  const keyReady = provider.credentialState === "configured" || provider.credentialState === "not_required";
  return (
    <div className={styles.connectionWorkspace}>
      <div className={styles.connectionLead} role="note">
        <strong>一个中转站 / Provider = 一把 API Key</strong>
        <span>
          下方 Key 对该 Provider 下<strong>全部固定模型共用</strong>，不必按模型重复填写。
          上下文窗口也是 Provider 级兜底（token 数）；未填时依赖发现结果，缺失会导致 Agent 启动失败。
        </span>
      </div>

      <section className={styles.connectionCard} aria-label="API Key">
        <header className={styles.connectionCardHeader}>
          <div>
            <p className={styles.connectionCardEyebrow}>1 · API Key</p>
            <h3 className={styles.connectionCardTitle}>全站共用凭据</h3>
          </div>
          <VStatusChip tone={keyReady ? "success" : "warning"}>
            {provider.credentialState === "not_required"
              ? "无需 Key"
              : provider.credentialState === "configured"
                ? "已配置"
                : "未配置"}
          </VStatusChip>
        </header>
        {needsKey ? (
          credentialActive ? (
            <div className={styles.inlineCredential}>
              <p className={styles.muted}>
                写入草稿后，点页面右上角「保存到外部配置」才会落到环境变量；不会写进 config.toml 明文。
              </p>
              <label className={styles.inlineCredentialField}>
                <span>API Key</span>
                <VInput
                  type="password"
                  autoComplete="new-password"
                  value={credentialValue}
                  disabled={disabled}
                  placeholder="粘贴中转站提供的 Key"
                  onChange={(event) => onCredentialValueChange(event.target.value)}
                />
              </label>
              <VActionGroup ariaLabel="API Key 操作">
                <VButton isDisabled={disabled} onPress={onCancelCredential}>取消</VButton>
                <VButton
                  variant="primary"
                  isDisabled={disabled || !credentialValue.trim()}
                  onPress={onSaveCredential}
                >
                  保存 Key 到草稿
                </VButton>
              </VActionGroup>
            </div>
          ) : (
            <div className={styles.connectionCardBody}>
              <p className={styles.muted}>
                {provider.credentialState === "configured"
                  ? "已有 Key。需要轮换时点下方按钮更新（仍是这一把，覆盖全站模型）。"
                  : "还没有 Key。中转站通常只发一把 Key，配一次即可调用该站所有固定模型。"}
              </p>
              <VButton variant="primary" isDisabled={disabled} onPress={onEditCredential}>
                {provider.credentialState === "configured" ? "更新 API Key" : "填写 API Key"}
              </VButton>
            </div>
          )
        ) : (
          <p className={styles.muted}>此 Provider 声明为无需凭据。</p>
        )}
      </section>

      <section className={styles.connectionCard} aria-label="上下文窗口">
        <header className={styles.connectionCardHeader}>
          <div>
            <p className={styles.connectionCardEyebrow}>2 · 上下文窗口</p>
            <h3 className={styles.connectionCardTitle}>context_window（token）</h3>
          </div>
          <VStatusChip tone={provider.contextWindow ? "success" : "warning"}>
            {provider.contextWindow ? `${provider.contextWindow}` : "未配置"}
          </VStatusChip>
        </header>
        <div className={styles.connectionCardBody}>
          <p className={styles.muted}>
            填中转站/模型真实上限，例如 32000、128000。一个 Provider 共用此兜底值；保存草稿后记得顶部「保存到外部配置」。
          </p>
          <label className={styles.inlineCredentialField}>
            <span>上下文窗口</span>
            <VInput
              type="number"
              min={1}
              step={1}
              value={contextWindowDraft}
              disabled={disabled}
              placeholder="例如 128000"
              onChange={(event) => onContextWindowDraftChange(event.target.value)}
            />
          </label>
          <VButton variant="primary" isDisabled={disabled} onPress={onSaveContextWindow}>
            保存上下文窗口到草稿
          </VButton>
        </div>
      </section>

      <div className={styles.detailGrid}>
        <span className={styles.fact}>
          <small className={styles.factLabel}>服务端点</small>
          <strong className={styles.factValue} title={provider.baseUrl || "未配置"}>{provider.baseUrl || "未配置"}</strong>
        </span>
        <span className={styles.fact}>
          <small className={styles.factLabel}>驱动 / 类型</small>
          <strong className={styles.factValue}>{provider.driver || "未配置"} · {provider.serviceClass || "未配置"}</strong>
        </span>
        {provider.serviceClass === "local_runtime" ? (
          <VSection className={`${styles.deployment} col-span-full`} title="本地部署" meta="与模型 upstream ID 分离">
            <div className={styles.detailGrid}>
              <span className={styles.fact}>
                <small className={styles.factLabel}>Runtime framework</small>
                <strong className={styles.factValue}>{provider.runtimeFramework || "未知"}</strong>
              </span>
              <span className={styles.fact}>
                <small className={styles.factLabel}>Artifact path</small>
                <strong className={styles.factValue} title={provider.artifactPath || "未配置"}>{provider.artifactPath || "未配置"}</strong>
              </span>
            </div>
          </VSection>
        ) : null}
      </div>
    </div>
  );
}

export type ProviderModelsTabProps = {
  provider: ProviderRegistryRow;
  disabled: boolean;
  modelQuery: string;
  modelFilter: ProviderModelFilter;
  liveReferenceCountByModelRef: Record<string, number>;
  onQueryChange: (query: string) => void;
  onFilterChange: (filter: ProviderModelFilter) => void;
  onPin: (providerId: string, models: ConfigCatalogModel[]) => void;
  onUnpin: (modelRef: string) => void;
  onTestModel: (modelRef: string) => void;
  imageCapabilityBusy?: boolean;
  pinBusy?: boolean;
  onProbeImageInput?: (modelRef: string) => void;
  reasoningFeedbackByModelRef?: Record<string, {
    phase: "busy" | "success" | "error";
    values: string[];
    message: string;
  }>;
  onProbeReasoning?: (modelRef: string) => void;
};

export function ProviderModelsTab({
  provider,
  disabled,
  modelQuery,
  modelFilter,
  liveReferenceCountByModelRef,
  onQueryChange,
  onFilterChange,
  onPin,
  onUnpin,
  onTestModel,
  imageCapabilityBusy = false,
  pinBusy = false,
  onProbeImageInput,
  reasoningFeedbackByModelRef = {},
  onProbeReasoning,
}: ProviderModelsTabProps) {
  const summary = useMemo(() => summarizeProviderModels(provider.models), [provider.models]);
  const pinnableModels = useMemo(() => pinnableProviderModels(provider.models), [provider.models]);
  const visibleModels = useMemo(
    () => filterProviderModels(provider.models, modelQuery, modelFilter),
    [modelFilter, modelQuery, provider.models],
  );
  const emptyText = provider.models.length === 0
    ? "该 Provider 暂无模型。先点右上角「发现」。"
    : modelFilter === "pinned" && summary.pinned === 0
      ? "还没有固定模型。用上方「固定全部已发现」一键加入，或在「已发现」里逐个点「固定到配置」。"
      : modelFilter === "discovered" && summary.discovered === 0
        ? "没有已发现模型。先运行「发现」，或切换到「全部」。"
        : "没有匹配的模型。请调整搜索或筛选条件。";

  return (
    <div className={styles.modelsWorkspace}>
      <div className={styles.modelToolbar}>
        <VInput
          aria-label="搜索模型"
          className={styles.modelSearch}
          placeholder="搜索 modelRef、Upstream ID 或名称"
          value={modelQuery}
          onChange={(event) => onQueryChange(event.currentTarget.value)}
        />
        <VActionGroup ariaLabel="模型状态筛选" className={styles.modelFilters}>
          {MODEL_FILTERS.map((filter) => (
            <VButton
              key={filter.id}
              density="compact"
              variant={modelFilter === filter.id ? "primary" : "ghost"}
              aria-pressed={modelFilter === filter.id}
              onPress={() => onFilterChange(filter.id)}
            >
              {filter.label} {summary[filter.countKey]}
            </VButton>
          ))}
        </VActionGroup>
      </div>
      {pinnableModels.length > 0 ? (
        <div className={styles.pinBanner} role="region" aria-label="批量固定模型">
          <div className={styles.pinBannerCopy}>
            <strong>发现 {pinnableModels.length} 个可固定模型</strong>
            <span>
              「发现」不等于已入库。点「固定全部已发现」一次写入模型库；保存配置后即可在 Agent 里选用。也可在表格里逐个点「固定到配置」。
            </span>
          </div>
          <VActionGroup ariaLabel="批量固定操作" className={styles.pinBannerActions}>
            <VButton
              variant="primary"
              data-model-action="pin-all"
              isDisabled={disabled || pinBusy}
              title={
                pinBusy
                  ? "正在固定模型…"
                  : provider.refreshDue
                    ? `目录可能已过期，仍可固定当前列表中的 ${pinnableModels.length} 个已发现模型；建议稍后点「发现模型」刷新`
                    : `固定全部 ${pinnableModels.length} 个已发现模型`
              }
              onPress={() => onPin(provider.providerId, pinnableModels)}
            >
              {pinBusy ? "正在固定…" : `固定全部已发现（${pinnableModels.length}）`}
            </VButton>
            {modelFilter !== "discovered" ? (
              <VButton
                density="compact"
                variant="ghost"
                onPress={() => onFilterChange("discovered")}
              >
                只看已发现
              </VButton>
            ) : null}
          </VActionGroup>
        </div>
      ) : null}
      {modelFilter === "pinned" && summary.pinned === 0 && summary.discovered > 0 ? (
        <p className={styles.modelFilterHint} role="status">
          还没有已固定模型。推荐直接点「固定全部已发现」，不必一个个勾选。
          <VButton
            density="compact"
            variant="primary"
            className={styles.modelFilterHintAction}
            isDisabled={disabled || pinBusy}
            onPress={() => onPin(provider.providerId, pinnableModels)}
          >
            {pinBusy ? "正在固定…" : `固定全部（${pinnableModels.length}）`}
          </VButton>
        </p>
      ) : null}
      <div className={styles.tableScroll}>
        <VDenseTable
          ariaLabel={`${provider.label} 模型目录`}
          className={styles.table}
          rows={visibleModels}
          getRowKey={(model) => model.modelRef}
          emptyText={emptyText}
          columns={[
          {
            id: "model-ref",
            header: "Canonical modelRef",
            className: "w-[23%]",
            render: (model) => (
              <span className={styles.modelIdentity} data-model-availability={model.availability}>
                <strong className={styles.ellipsis} title={model.modelRef}>{model.modelRef}</strong>
                <small className={styles.muted}>{model.label || model.modelKey}</small>
              </span>
            ),
          },
          {
            id: "upstream",
            header: "Upstream ID",
            className: "w-[18%]",
            render: (model) => <span className={styles.ellipsis} title={model.upstreamId}>{model.upstreamId}</span>,
          },
          { id: "availability", header: "可用性", className: "w-[11%]", render: (model) => <VStatusChip tone={model.availability === "disabled" ? "danger" : "neutral"}>{model.availability}</VStatusChip> },
          {
            id: "verification",
            header: "真实调用",
            className: "w-[18%]",
            render: (model) => {
              const verificationStatus = model.verificationStatus || "unverified";
              const errorLabel = (() => {
                const kind = String(model.verificationErrorType || "").trim();
                if (!kind) return "";
                if (kind === "timeout") return "超时";
                if (kind === "bad_request") return "上游 400 拒绝";
                if (kind === "auth_failed") return "鉴权失败";
                if (kind === "rate_limited") return "限流";
                if (kind === "not_found") return "模型不存在";
                if (kind === "network") return "网络错误";
                if (kind === "missing_credential") return "缺 Key";
                if (kind === "service_unavailable" || kind === "upstream_unavailable") return "上游不可用";
                return kind;
              })();
              const detail = [
                model.verificationHttpStatus ? `HTTP ${model.verificationHttpStatus}` : "",
                errorLabel,
                model.verificationMessage || "",
                model.verificationCheckedAt || (verificationStatus === "unverified" ? "未测试" : ""),
              ].filter(Boolean).join(" · ");
              return (
                <span className={styles.providerIdentity}>
                  <VStatusChip tone={verificationStatus === "verified" ? "success" : verificationStatus === "failed" ? "danger" : "warning"}>
                    {verificationStatus === "verified" ? "verified · 可调用" : verificationStatus === "failed" ? "failed · 调用失败" : "unverified · 未测试"}
                  </VStatusChip>
                  <small className={styles.muted} title={detail || undefined}>{detail || "—"}</small>
                </span>
              );
            },
          },
          { id: "capabilities", header: "能力来源", className: "w-[13%]", render: (model) => <CapabilityList model={model} /> },
          {
            id: "actions",
            header: "操作",
            className: "w-[17%]",
            align: "right",
            render: (model) => {
              const action = deriveProviderModelActionState(
                provider,
                model,
                liveReferenceCountByModelRef[model.modelRef] ?? 0,
                disabled,
              );
              const testAvailable = canTestProviderModel(model);
              const imageCapability = model.capabilities?.image_input;
              const imageProbeAvailable = (
                ["observed", "pinned"].includes(model.availability)
                && !provider.refreshDue
              );
              const reasoningFeedback = reasoningFeedbackByModelRef[model.modelRef];
              const reasoningValues = reasoningFeedback?.phase === "success"
                ? reasoningFeedback.values
                : model.reasoningEffortValues ?? [];
              const reasoningSource = String(model.reasoningCapabilitySource || "");
              const reasoningDeclared = (
                reasoningValues.length > 0
                && (
                  reasoningSource === "operator_override"
                  || model.reasoningVerificationStatus === "declared"
                )
              );
              const reasoningVerified = reasoningFeedback?.phase === "success"
                || model.reasoningVerificationStatus === "verified";
              const reasoningHasContract = reasoningDeclared || reasoningVerified || reasoningValues.length > 0;
              // T6: probe is optional evidence; operator declaration already enables UI (D1).
              const reasoningProbeAvailable = (
                provider.defaultProtocol === "responses"
                && ["observed", "pinned"].includes(model.availability)
                && !reasoningHasContract
                && !provider.refreshDue
              );
              return (
                <VActionGroup ariaLabel={`${model.modelRef} 模型操作`}>
                  {imageProbeAvailable ? (
                    <VButton
                      data-model-capability-action="image_input"
                      density="compact"
                      icon={<ImageIcon size={14} />}
                      isDisabled={disabled || imageCapabilityBusy}
                      title="发送一张最小有效图片，验证当前模型路由是否支持图像输入，并保存运行时能力证据。"
                      onPress={() => onProbeImageInput?.(model.modelRef)}
                    >
                      {imageCapabilityBusy
                        ? "验证图片中…"
                        : imageCapability?.value === "supported" || imageCapability?.value === "unsupported"
                          ? "重新验证图片"
                          : "验证图片输入"}
                    </VButton>
                  ) : null}
                  {reasoningHasContract ? (
                    <span
                      className={styles.modelActionState}
                      data-model-reasoning={reasoningDeclared && !reasoningVerified ? "declared" : "verified"}
                      title={
                        reasoningDeclared && !reasoningVerified
                          ? "运营协议合同已声明；Composer 可显示档位。可选再验证 low/high 取证。"
                          : "运行时验证已保存能力证据。完整档位仍以运营协议合同为准。"
                      }
                    >
                      {reasoningDeclared && !reasoningVerified
                        ? `协议已声明 ${reasoningValues.join(" / ")}`
                        : `推理 ${reasoningValues.join(" / ")} 已验证`}
                    </span>
                  ) : reasoningProbeAvailable ? (
                    <VButton
                      density="compact"
                      isDisabled={disabled || reasoningFeedback?.phase === "busy"}
                      title="一期探测仅验证 low/high + reasoning_object（Responses）。成功后保存能力证据；完整档位（medium/xhigh 等）请在 pin defaults 写协议合同。"
                      onPress={() => onProbeReasoning?.(model.modelRef)}
                    >
                      {reasoningFeedback?.phase === "busy" ? "验证推理中…" : "验证推理 low / high"}
                    </VButton>
                  ) : null}
                  {action.kind === "pin" ? (
                    <VButton
                      variant="primary"
                      density="compact"
                      data-model-action="pin"
                      isDisabled={action.disabled || pinBusy}
                      title={action.reason}
                      onPress={() => onPin(provider.providerId, [model])}
                    >
                      {pinBusy ? "固定中…" : action.label}
                    </VButton>
                  ) : null}
                  {testAvailable ? (
                    <VButton
                      density="compact"
                      isDisabled={disabled}
                      title="发送最小真实模型请求并保存脱敏结果。"
                      onPress={() => onTestModel(model.modelRef)}
                    >
                      测试调用
                    </VButton>
                  ) : null}
                  {action.kind === "unpin" ? (
                    <VButton
                      variant="danger"
                      density="compact"
                      isDisabled={action.disabled}
                      title={action.reason || undefined}
                      onPress={() => onUnpin(model.modelRef)}
                    >
                      {action.label}
                    </VButton>
                  ) : action.kind === "in_use" || action.kind === "unavailable" ? (
                    <span className={styles.modelActionState} data-model-action={action.kind}>
                      {action.label}{action.kind === "in_use" ? ` · ${action.referenceCount} 个引用` : ""}
                    </span>
                  ) : null}
                  {reasoningFeedback?.phase === "error" ? (
                    <small className={styles.critical} role="alert">{reasoningFeedback.message}</small>
                  ) : null}
                </VActionGroup>
              );
            },
          },
          ]}
        />
      </div>
    </div>
  );
}

function ProtocolsTab({ provider }: { provider: ProviderRegistryRow }) {
  return (
    <div className={styles.tabSurface}>
      <span className={styles.fact}>
        <small className={styles.factLabel}>默认 wire protocol</small>
        <strong className={styles.factValue}>{provider.defaultProtocol || "unknown"}</strong>
      </span>
      {provider.models.length ? provider.models.map((model) => (
        <span key={model.modelRef} className={styles.fact} data-model-availability={model.availability}>
          <small className={styles.factLabel} title={model.modelRef}>{model.modelRef}</small>
          <CapabilityList model={model} />
        </span>
      )) : <VStateSurface tone="empty" title="暂无能力观测">运行发现后，unknown 与 unsupported 会分别显示。</VStateSurface>}
    </div>
  );
}

function DiagnosticsTab({
  provider,
  disabled,
  onDiscover,
}: {
  provider: ProviderRegistryRow;
  disabled: boolean;
  onDiscover: (providerId: string) => void;
}) {
  const isCritical = ["auth_failed", "protocol_mismatch", "blocked", "discovery_failed"].includes(provider.status);
  return (
    <div className={styles.tabSurface}>
      {isCritical ? (
        <p className={styles.critical} role="alert">
          当前 Provider 状态为 {provider.status}。请修复认证或协议后再用于运行路由。
        </p>
      ) : null}
      <VStateSurface
        tone={isCritical ? "error" : provider.refreshDue ? "unavailable" : "info"}
        title={provider.refreshDue ? "目录已 stale，需要刷新" : "Provider 诊断"}
        facts={[
          { key: "attempt", label: "最近尝试", value: provider.lastAttemptAt || "从未" },
          { key: "success", label: "最近成功", value: provider.lastSuccessAt || "从未" },
          { key: "failure", label: "最近失败原因", value: discoveryErrorLabel(provider.lastErrorType ?? "") },
          { key: "auth", label: "认证", value: provider.status === "auth_failed" ? "失败" : provider.credentialState },
          { key: "protocol", label: "协议", value: provider.status === "protocol_mismatch" ? "不匹配" : provider.defaultProtocol || "unknown" },
        ]}
        actions={(
          <VButton
            variant="primary"
            icon={<RefreshCw size={14} />}
            isDisabled={disabled}
            onPress={() => onDiscover(provider.providerId)}
          >
            重新发现
          </VButton>
        )}
      >
        诊断只展示有界状态，不展示原始响应或凭据内容。
      </VStateSurface>
    </div>
  );
}

export function ConfigProviderRegistryPanel({
  rows,
  selectedProviderId,
  selectedTab,
  disabled,
  activeCredentialProviderId,
  credentialValue,
  activeRouteProviderId,
  imageCapabilityBusy,
  actionFeedback,
  liveReferenceCountByModelRef,
  hasPendingApply = false,
  canSaveConfig = false,
  saveBusy = false,
  onSaveExternal,
  onSelectProvider,
  onSelectTab,
  onDiscover,
  onEditCredential,
  onCredentialValueChange,
  onCancelCredential,
  onSaveCredential,
  onSaveContextWindow,
  onEditRoute,
  onPin,
  onUnpin,
  onTestModel,
  onProbeImageInput,
  onDeleteProvider,
}: ConfigProviderRegistryPanelProps) {
  const orderedRows = useMemo(() => sortProviderRegistryRows(rows), [rows]);
  // Asset home: credential-ready only; primary list hides auth/discovery failures.
  const readyRows = useMemo(() => filterReadyProviderAssets(orderedRows), [orderedRows]);
  const { healthy: healthyRows, abnormal: abnormalRows } = useMemo(
    () => partitionReadyProviderAssets(readyRows),
    [readyRows],
  );
  const [showAbnormalAssets, setShowAbnormalAssets] = useState(false);
  const visibleSidebarRows = useMemo(
    () => (showAbnormalAssets ? [...healthyRows, ...abnormalRows] : healthyRows),
    [abnormalRows, healthyRows, showAbnormalAssets],
  );
  const provider =
    visibleSidebarRows.find((row) => row.providerId === selectedProviderId)
    ?? healthyRows.find((row) => row.providerId === selectedProviderId)
    ?? readyRows.find((row) => row.providerId === selectedProviderId)
    ?? healthyRows[0]
    ?? readyRows[0]
    ?? null;
  const [modelQuery, setModelQuery] = useState("");
  const [contextWindowDraft, setContextWindowDraft] = useState("");
  const [modelFilter, setModelFilter] = useState<ProviderModelFilter>(() =>
    defaultProviderModelFilter(provider?.models ?? []),
  );
  const [showAdvancedTools, setShowAdvancedTools] = useState(false);

  useEffect(() => {
    if (!provider) {
      setContextWindowDraft("");
      return;
    }
    setContextWindowDraft(provider.contextWindow ? String(provider.contextWindow) : "");
  }, [provider?.providerId, provider?.contextWindow]);

  // Prefer a healthy asset when selection is empty or points at a filtered-out row.
  useEffect(() => {
    const pool = showAbnormalAssets ? readyRows : healthyRows.length ? healthyRows : readyRows;
    if (!pool.length) return;
    if (selectedProviderId && pool.some((row) => row.providerId === selectedProviderId)) return;
    // Selected abnormal while collapsed → expand abnormal section instead of jumping away.
    if (
      selectedProviderId
      && abnormalRows.some((row) => row.providerId === selectedProviderId)
      && !showAbnormalAssets
    ) {
      setShowAbnormalAssets(true);
      return;
    }
    onSelectProvider(pool[0].providerId);
  }, [abnormalRows, healthyRows, onSelectProvider, readyRows, selectedProviderId, showAbnormalAssets]);

  const [mergePreview, setMergePreview] = useState<ConfigProviderMergePreview | null>(null);
  const [mergeResult, setMergeResult] = useState<ConfigProviderMergeResult | null>(null);
  const [mergeConfirmed, setMergeConfirmed] = useState(false);
  const [mergeBusy, setMergeBusy] = useState(false);
  const [mergeError, setMergeError] = useState("");
  const [reasoningFeedbackByModelRef, setReasoningFeedbackByModelRef] = useState<Record<string, {
    phase: "busy" | "success" | "error";
    values: string[];
    message: string;
  }>>({});
  const mergeCandidate = useMemo(
    () => deriveProviderMergeCandidate(orderedRows, provider?.providerId ?? ""),
    [provider?.providerId, orderedRows],
  );
  const providerLiveReferenceCount = provider?.models.reduce(
    (total, model) => total + (liveReferenceCountByModelRef[model.modelRef] ?? 0),
    0,
  ) ?? 0;
  const providerDeleteBlocked = Boolean(provider && (provider.pinnedCount > 0 || providerLiveReferenceCount > 0));
  const visibleFeedback = actionFeedback?.providerId === provider?.providerId ? actionFeedback : null;
  const discoverBusy = visibleFeedback?.kind === "discover" && visibleFeedback.phase === "busy";
  const pinBusy = visibleFeedback?.kind === "pin" && visibleFeedback.phase === "busy";
  const credentialActive = activeCredentialProviderId === provider?.providerId;
  const routeActive = activeRouteProviderId === provider?.providerId;

  useEffect(() => {
    setModelQuery("");
    setModelFilter(defaultProviderModelFilter(provider?.models ?? []));
    setMergePreview(null);
    setMergeResult(null);
    setMergeConfirmed(false);
    setMergeError("");
    setReasoningFeedbackByModelRef({});
    // Reset table tools when switching Provider only — keep user filter while discovering on same Provider.
  }, [provider?.providerId]);

  // After a successful pin batch, force the「已固定」filter so users see the full pinned set.
  useEffect(() => {
    if (actionFeedback?.kind !== "pin" || actionFeedback.phase !== "success") return;
    if (actionFeedback.providerId !== provider?.providerId) return;
    setModelFilter("pinned");
    setModelQuery("");
  }, [actionFeedback, provider?.providerId]);

  const probeReasoning = async (modelRef: string) => {
    setReasoningFeedbackByModelRef((current) => ({
      ...current,
      [modelRef]: { phase: "busy", values: [], message: "正在验证 low/high…" },
    }));
    try {
      const result = await fetchJson<ConfigLlmTestResult>("/api/config/test-llm", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ modelId: modelRef, capability: "reasoning_effort" }),
      });
      if (!result.ok || !result.reasoning_contract_persisted) {
        throw new Error(result.message || "推理能力验证失败");
      }
      const values = result.reasoning_effort_values ?? [];
      setReasoningFeedbackByModelRef((current) => ({
        ...current,
        [modelRef]: {
          phase: "success",
          values,
          message: `已验证并保存 ${values.join(" / ")}（一期仅 low/high；完整档位请写 pin defaults 协议合同）`,
        },
      }));
    } catch (error) {
      setReasoningFeedbackByModelRef((current) => ({
        ...current,
        [modelRef]: {
          phase: "error",
          values: [],
          message: error instanceof Error ? error.message : String(error),
        },
      }));
    }
  };

  const previewMerge = async () => {
    if (!mergeCandidate) return;
    setMergeBusy(true);
    setMergeError("");
    try {
      const credentialDecisions = Object.fromEntries(
        mergeCandidate.duplicateProviderIds.map((providerId) => [providerId, "use_canonical"]),
      );
      const preview = await fetchJson<ConfigProviderMergePreview>(
        "/api/config/migration/providers/merge/preview",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ...mergeCandidate, credentialDecisions }),
        },
      );
      setMergePreview(preview);
      setMergeConfirmed(false);
    } catch (error) {
      setMergeError(error instanceof Error ? error.message : String(error));
    } finally {
      setMergeBusy(false);
    }
  };

  const applyMerge = async () => {
    if (!mergePreview || !mergeConfirmed) return;
    setMergeBusy(true);
    setMergeError("");
    try {
      const result = await fetchJson<ConfigProviderMergeResult>(
        "/api/config/migration/providers/merge/apply",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            previewId: mergePreview.previewId,
            baseHash: mergePreview.baseHash,
            confirmed: true,
          }),
        },
      );
      setMergeResult(result);
    } catch (error) {
      setMergeError(error instanceof Error ? error.message : String(error));
    } finally {
      setMergeBusy(false);
    }
  };

  const rollbackMerge = async () => {
    if (!mergeResult) return;
    setMergeBusy(true);
    setMergeError("");
    try {
      const result = await fetchJson<ConfigProviderMergeResult>(
        `/api/config/migration/providers/merge/${encodeURIComponent(mergeResult.migrationId)}/rollback`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ migrationId: mergeResult.migrationId, baseHash: mergeResult.hash }),
        },
      );
      setMergeResult(result);
      setMergePreview(null);
      setMergeConfirmed(false);
    } catch (error) {
      setMergeError(error instanceof Error ? error.message : String(error));
    } finally {
      setMergeBusy(false);
    }
  };

  const [inspectorOpen, setInspectorOpen] = useState(false);
  const inspectorProvider = inspectorOpen ? provider : null;

  function openInspector(providerId: string) {
    onSelectProvider(providerId);
    onSelectTab("connection");
    setInspectorOpen(true);
  }

  function closeInspector() {
    setInspectorOpen(false);
    onCancelCredential();
  }

  const saveContextWindowFor = (target: ProviderRegistryRow) => {
    const raw = contextWindowDraft.trim();
    if (!raw) {
      onSaveContextWindow(target.providerId, null);
      return;
    }
    const parsed = Number(raw);
    if (!Number.isFinite(parsed) || parsed <= 0) return;
    onSaveContextWindow(target.providerId, Math.round(parsed));
  };

  return (
    <VSurface as="section" id="config-models" className={styles.sectionSurface} padding="none">
      <VPanelHeader
        className={styles.header}
        eyebrow="模型资产"
        title="已配置的连接与模型"
        actions={(
          <VStatusChip tone={hasPendingApply ? "warning" : disabled ? "warning" : "success"}>
            {disabled ? "只读 / 忙碌" : hasPendingApply ? "有未保存修改" : "已与草稿同步"}
          </VStatusChip>
        )}
      />
      <p className={styles.workspaceLead} role="note">
        左栏默认只显示<strong>可用服务</strong>（已配 Key 且连接正常）。异常服务收在下方折叠区；新厂商请用「② 添加连接」。
      </p>
      {hasPendingApply ? (
        <div className={styles.savePrompt} role="status" data-save-prompt="pending" aria-live="polite">
          <div className={styles.savePromptCopy}>
            <strong>有未保存的模型配置</strong>
            <span>固定模型 / API Key / 上下文窗口仍在草稿。必须点「保存到外部配置」才会写入 operator config.toml 并被 Agent 使用。</span>
          </div>
          <VButton
            variant="primary"
            data-save-prompt-action="apply"
            icon={<Save size={14} />}
            isDisabled={!canSaveConfig || disabled || saveBusy}
            onPress={() => onSaveExternal?.()}
          >
            {saveBusy ? "保存中…" : "保存到外部配置"}
          </VButton>
        </div>
      ) : null}
      <VSplitWorkspace
        className={inspectorOpen ? styles.registryWorkspaceTriple : styles.registryWorkspace}
        columnsClassName={
          inspectorOpen
            ? "grid-cols-[minmax(18rem,22rem)_minmax(0,1fr)_minmax(18rem,22rem)]"
            : "grid-cols-[minmax(18rem,22rem)_minmax(0,1fr)]"
        }
        resize={{
          layoutId: WORKBENCH_LAYOUT_IDS.configModelAssets,
          sidebar: { defaultWidth: 320, minWidth: 260, maxWidth: 420 },
          aside: { defaultWidth: 320, minWidth: 260, maxWidth: 440 },
        }}
        sidebar={(
          <div className={styles.providerRail}>
            <div className={styles.providerListSection}>
              <p className={styles.providerListHeading}>可用服务 · {healthyRows.length}</p>
              <VEntityList
                ariaLabel="可用服务列表"
                activeId={provider?.providerId}
                className={styles.providerList}
                items={healthyRows.map((row) => ({ ...row, id: row.providerId }))}
                empty={(
                  <VStateSurface tone="empty" title="暂无可用服务">
                    {abnormalRows.length
                      ? "当前仅有异常服务。可展开下方「异常服务」处理，或点「② 添加连接」。"
                      : "请点上方「② 添加连接」接入中转站并保存 Key。"}
                  </VStateSurface>
                )}
                renderItem={(row) => (
                  <ProviderAssetRow
                    row={row}
                    selected={provider?.providerId === row.providerId}
                    inspecting={inspectorOpen && provider?.providerId === row.providerId}
                    disabled={disabled}
                    onSelect={() => onSelectProvider(row.providerId)}
                    onEdit={() => openInspector(row.providerId)}
                  />
                )}
              />
            </div>
            {abnormalRows.length > 0 ? (
              <div className={styles.abnormalSection} data-abnormal-assets="true">
                <VButton
                  className={styles.abnormalToggle}
                  density="compact"
                  variant="ghost"
                  contentLayout="plain"
                  aria-expanded={showAbnormalAssets}
                  data-abnormal-expanded={showAbnormalAssets ? "true" : "false"}
                  onPress={() => setShowAbnormalAssets((open) => !open)}
                >
                  <span>
                    异常服务 · {abnormalRows.length}
                    <small>认证失败 / 发现失败等，默认折叠</small>
                  </span>
                  <span>{showAbnormalAssets ? "收起" : "展开"}</span>
                </VButton>
                {showAbnormalAssets ? (
                  <VEntityList
                    ariaLabel="异常服务列表"
                    activeId={provider?.providerId}
                    className={styles.providerList}
                    items={abnormalRows.map((row) => ({ ...row, id: row.providerId }))}
                    renderItem={(row) => (
                      <ProviderAssetRow
                        row={row}
                        selected={provider?.providerId === row.providerId}
                        inspecting={inspectorOpen && provider?.providerId === row.providerId}
                        disabled={disabled}
                        onSelect={() => onSelectProvider(row.providerId)}
                        onEdit={() => openInspector(row.providerId)}
                      />
                    )}
                  />
                ) : null}
              </div>
            ) : null}
          </div>
        )}
        main={provider ? (
          <div className={styles.modelsColumn} data-provider-status={provider.status} data-vui-region="config-models-main">
            <div className={styles.detailHeader}>
              <span className={styles.detailIdentity}>
                <strong title={provider.providerId}>{provider.label || provider.providerId}</strong>
                <small className={styles.muted}>
                  {provider.providerId} · 已固定 {provider.pinnedCount}
                  {provider.contextWindow ? ` · 窗口 ${provider.contextWindow}` : " · 窗口未配置"}
                </small>
              </span>
              <VActionGroup ariaLabel="模型库操作" className={styles.actions}>
                <VButton
                  data-provider-action="discover"
                  variant="primary"
                  icon={<RefreshCw size={14} />}
                  isDisabled={disabled}
                  title="从中转站 / 上游拉取模型目录（发现后还需固定才会入库）"
                  onPress={() => onDiscover(provider.providerId)}
                >
                  {discoverBusy ? "发现中…" : "发现模型"}
                </VButton>
                <VButton
                  data-provider-action="edit-asset"
                  icon={<Pencil size={14} />}
                  variant={inspectorOpen ? "primary" : "secondary"}
                  isDisabled={disabled}
                  onPress={() => openInspector(provider.providerId)}
                >
                  编辑配置
                </VButton>
              </VActionGroup>
            </div>
            {visibleFeedback ? (
              <p
                className={
                  visibleFeedback.phase === "error"
                    ? styles.actionFeedbackError
                    : visibleFeedback.phase === "success"
                      ? styles.actionFeedbackSuccess
                      : styles.actionFeedback
                }
                data-feedback-phase={visibleFeedback.phase}
                data-feedback-kind={visibleFeedback.kind}
                role={visibleFeedback.phase === "error" ? "alert" : "status"}
                aria-live="polite"
              >
                {visibleFeedback.message}
              </p>
            ) : null}
            <div className={styles.detailBody} data-provider-tab="models">
              <ProviderModelsTab
                provider={provider}
                disabled={disabled}
                modelQuery={modelQuery}
                modelFilter={modelFilter}
                liveReferenceCountByModelRef={liveReferenceCountByModelRef}
                onQueryChange={setModelQuery}
                onFilterChange={setModelFilter}
                onPin={onPin}
                onUnpin={onUnpin}
                onTestModel={onTestModel}
                imageCapabilityBusy={imageCapabilityBusy}
                pinBusy={pinBusy}
                onProbeImageInput={onProbeImageInput}
                reasoningFeedbackByModelRef={reasoningFeedbackByModelRef}
                onProbeReasoning={(modelRef) => void probeReasoning(modelRef)}
              />
            </div>
          </div>
        ) : (
          <VStateSurface tone="empty" icon={<Database size={16} />} title="选择左侧已配置服务">点选服务查看已固定模型；点「编辑」在右侧改配置。</VStateSurface>
        )}
        aside={inspectorProvider ? (
          <div className={styles.inspectorPanel} data-vui-region="config-asset-inspector" data-provider-id={inspectorProvider.providerId}>
            <div className={styles.inspectorHeader}>
              <div className={styles.detailIdentity}>
                <p className={styles.connectionCardEyebrow}>资产配置</p>
                <strong title={inspectorProvider.providerId}>{inspectorProvider.label || inspectorProvider.providerId}</strong>
                <small className={styles.muted}>API Key · 上下文窗口 · 连接</small>
              </div>
              <VButton
                density="compact"
                variant="ghost"
                isIconOnly
                aria-label="关闭配置栏"
                icon={<X size={16} />}
                onPress={closeInspector}
              />
            </div>
            <div className={styles.inspectorBody}>
              <ConnectionTab
                provider={inspectorProvider}
                contextWindowDraft={contextWindowDraft}
                credentialActive={credentialActive && activeCredentialProviderId === inspectorProvider.providerId}
                credentialValue={credentialValue}
                disabled={disabled}
                onContextWindowDraftChange={setContextWindowDraft}
                onSaveContextWindow={() => saveContextWindowFor(inspectorProvider)}
                onEditCredential={() => onEditCredential(inspectorProvider.providerId)}
                onCredentialValueChange={onCredentialValueChange}
                onCancelCredential={onCancelCredential}
                onSaveCredential={() => onSaveCredential(inspectorProvider.providerId)}
              />
              <VActionGroup ariaLabel="进阶连接操作" className={styles.actions}>
                <VButton
                  data-provider-action="route"
                  icon={<Route size={14} />}
                  isDisabled={disabled}
                  onPress={() => onEditRoute(inspectorProvider.providerId)}
                >
                  修改路由
                </VButton>
                <VButton
                  density="compact"
                  variant="ghost"
                  isDisabled={disabled}
                  onPress={() => setShowAdvancedTools((open) => !open)}
                >
                  {showAdvancedTools ? "收起诊断" : "诊断 / 合并（高级）"}
                </VButton>
              </VActionGroup>
              {showAdvancedTools ? (
                <div className={styles.inspectorAdvanced}>
                  <DiagnosticsTab provider={inspectorProvider} disabled={disabled} onDiscover={onDiscover} />
                  {mergeCandidate ? (
                    <VSection
                      className={styles.mergeSection}
                      title="合并重复 Provider（高级）"
                      meta="仅当存在端点完全相同的重复项时使用；日常中转站不需要"
                    >
                      <div className={styles.mergeContent} data-provider-merge-status={mergePreview?.status ?? "idle"}>
                        <p className={styles.muted}>
                          保留 <strong>{mergeCandidate.canonicalProviderId}</strong>，候选重复项：{mergeCandidate.duplicateProviderIds.join("、")}。
                        </p>
                        {mergePreview ? (
                          <div className={styles.mergeFacts}>
                            <VStatusChip tone={mergePreview.status === "READY" ? "success" : "warning"}>{mergePreview.status}</VStatusChip>
                            <span>新增模型 {mergePreview.modelsToAdd.length}</span>
                          </div>
                        ) : null}
                        {mergeError ? <p className={styles.actionFeedbackError} role="alert">{mergeError}</p> : null}
                        <VActionGroup ariaLabel="重复 Provider 合并操作">
                          {!mergeResult ? (
                            <VButton isDisabled={disabled || mergeBusy} onPress={() => void previewMerge()}>
                              {mergeBusy ? "验证中…" : "生成合并预览"}
                            </VButton>
                          ) : null}
                          {mergePreview?.status === "READY" && !mergeResult ? (
                            <VButton
                              variant="danger"
                              isDisabled={disabled || mergeBusy || !mergeConfirmed}
                              onPress={() => void applyMerge()}
                            >
                              应用合并
                            </VButton>
                          ) : null}
                        </VActionGroup>
                        {mergePreview?.status === "READY" && !mergeResult ? (
                          <VCheckbox
                            className={styles.mergeConfirmation}
                            isSelected={mergeConfirmed}
                            isDisabled={disabled || mergeBusy}
                            onChange={setMergeConfirmed}
                          >
                            确认使用主 Provider 凭据并迁移引用
                          </VCheckbox>
                        ) : null}
                      </div>
                    </VSection>
                  ) : null}
                </div>
              ) : null}
              <div className={styles.dangerZone} data-provider-danger-zone="true">
                <VButton
                  variant="danger"
                  icon={<Trash2 size={14} />}
                  isDisabled={disabled || providerDeleteBlocked}
                  title={providerDeleteBlocked ? "先清除 pinned ownership 与 live references，才能删除 Provider。" : "删除 Provider 草稿"}
                  onPress={() => onDeleteProvider(inspectorProvider.providerId)}
                >
                  删除 Provider
                </VButton>
              </div>
            </div>
          </div>
        ) : undefined}
      />
    </VSurface>
  );
}
