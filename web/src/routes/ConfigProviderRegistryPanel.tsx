import { AlertTriangle, Database, RefreshCw, Route, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import {
  VActionGroup,
  VButton,
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
import type { ConfigCapabilityObservation, ConfigCatalogModel } from "../api/types";
import {
  canTestProviderModel,
  deriveProviderModelActionState,
  filterProviderModels,
  summarizeProviderModels,
  type ProviderModelFilter,
  type ProviderRegistryRow,
} from "./configProviderLogic";
import styles from "./ConfigProviderRegistryPanel.styles";

export type ConfigProviderRegistryTab = "connection" | "models" | "protocols" | "diagnostics";

export type ProviderActionKind = "discover" | "credential" | "route";

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
  activeRouteProviderId: string;
  actionFeedback: ProviderActionFeedback;
  liveReferenceCountByModelRef: Record<string, number>;
  onSelectProvider: (providerId: string) => void;
  onSelectTab: (tab: ConfigProviderRegistryTab) => void;
  onDiscover: (providerId: string) => void;
  onEditCredential: (providerId: string) => void;
  onEditRoute: (providerId: string) => void;
  onUnpin: (modelRef: string) => void;
  onTestModel: (modelRef: string) => void;
  onDeleteProvider: (providerId: string) => void;
};

const TABS: Array<{ id: ConfigProviderRegistryTab; label: string }> = [
  { id: "connection", label: "连接" },
  { id: "models", label: "模型" },
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

function capabilityTone(observation: ConfigCapabilityObservation): VStatusTone {
  if (observation.value === "supported") return "success";
  if (observation.value === "unsupported") return "danger";
  return "warning";
}

function CapabilityList({ model }: { model: ConfigCatalogModel }) {
  const capabilities = Object.entries(model.capabilities);
  if (!capabilities.length) {
    return <span className={styles.capabilityUnknown}>未观测</span>;
  }
  return (
    <div className={styles.capabilityList}>
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

function ConnectionTab({ provider }: { provider: ProviderRegistryRow }) {
  return (
    <div className={styles.detailGrid}>
      <span className={styles.fact}>
        <small className={styles.factLabel}>服务端点</small>
        <strong className={styles.factValue} title={provider.baseUrl || "未配置"}>{provider.baseUrl || "未配置"}</strong>
      </span>
      <span className={styles.fact}>
        <small className={styles.factLabel}>凭据状态</small>
        <strong className={styles.factValue}>{provider.credentialState}</strong>
      </span>
      <span className={styles.fact}>
        <small className={styles.factLabel}>驱动</small>
        <strong className={styles.factValue}>{provider.driver || "未配置"}</strong>
      </span>
      <span className={styles.fact}>
        <small className={styles.factLabel}>服务类型</small>
        <strong className={styles.factValue}>{provider.serviceClass || "未配置"}</strong>
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
  onUnpin: (modelRef: string) => void;
  onTestModel: (modelRef: string) => void;
};

export function ProviderModelsTab({
  provider,
  disabled,
  modelQuery,
  modelFilter,
  liveReferenceCountByModelRef,
  onQueryChange,
  onFilterChange,
  onUnpin,
  onTestModel,
}: ProviderModelsTabProps) {
  const summary = useMemo(() => summarizeProviderModels(provider.models), [provider.models]);
  const visibleModels = useMemo(
    () => filterProviderModels(provider.models, modelQuery, modelFilter),
    [modelFilter, modelQuery, provider.models],
  );
  const emptyText = provider.models.length === 0
    ? "该 Provider 暂无模型。先运行发现。"
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
              const detail = [
                model.verificationHttpStatus ? `HTTP ${model.verificationHttpStatus}` : "",
                model.verificationErrorType || "",
                model.verificationCheckedAt || "未测试",
              ].filter(Boolean).join(" · ");
              return (
                <span className={styles.providerIdentity}>
                  <VStatusChip tone={verificationStatus === "verified" ? "success" : verificationStatus === "failed" ? "danger" : "warning"}>
                    {verificationStatus === "verified" ? "verified · 可调用" : verificationStatus === "failed" ? "failed · 调用失败" : "unverified · 未测试"}
                  </VStatusChip>
                  <small className={styles.muted} title={detail}>{detail}</small>
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
              return (
                <VActionGroup ariaLabel={`${model.modelRef} 模型操作`}>
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
                  ) : (
                    <span className={styles.modelActionState} data-model-action={action.kind}>
                      {action.label}{action.kind === "in_use" ? ` · ${action.referenceCount} 个引用` : ""}
                    </span>
                  )}
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
    <div className={styles.detailSurface}>
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
    <div className={styles.detailSurface}>
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
  activeRouteProviderId,
  actionFeedback,
  liveReferenceCountByModelRef,
  onSelectProvider,
  onSelectTab,
  onDiscover,
  onEditCredential,
  onEditRoute,
  onUnpin,
  onTestModel,
  onDeleteProvider,
}: ConfigProviderRegistryPanelProps) {
  const [modelQuery, setModelQuery] = useState("");
  const [modelFilter, setModelFilter] = useState<ProviderModelFilter>("all");
  const provider = rows.find((row) => row.providerId === selectedProviderId) ?? rows[0];
  const items = rows.map((row) => ({ ...row, id: row.providerId }));
  const providerLiveReferenceCount = provider?.models.reduce(
    (total, model) => total + (liveReferenceCountByModelRef[model.modelRef] ?? 0),
    0,
  ) ?? 0;
  const providerDeleteBlocked = Boolean(provider && (provider.pinnedCount > 0 || providerLiveReferenceCount > 0));
  const visibleFeedback = actionFeedback?.providerId === provider?.providerId ? actionFeedback : null;
  const discoverBusy = visibleFeedback?.kind === "discover" && visibleFeedback.phase === "busy";
  const credentialActive = activeCredentialProviderId === provider?.providerId;
  const routeActive = activeRouteProviderId === provider?.providerId;

  useEffect(() => {
    setModelQuery("");
    setModelFilter("all");
  }, [selectedProviderId]);

  return (
    <VSurface as="section" id="config-models" className={styles.sectionSurface} padding="none">
      <VPanelHeader
        className={styles.header}
        eyebrow="Provider-first registry"
        title="Provider 与模型工作台"
        actions={<VStatusChip tone={disabled ? "warning" : "success"}>{disabled ? "只读 / 忙碌" : "草稿可编辑"}</VStatusChip>}
      />
      <VSplitWorkspace
        className={styles.registryWorkspace}
        sidebar={(
          <div className={styles.providerRail}>
            <VEntityList
              ariaLabel="Provider 列表"
              activeId={provider?.providerId}
              className={styles.providerList}
              items={items}
              empty={<VStateSurface tone="empty" title="尚无 Provider">使用右侧向导添加第一个 Provider。</VStateSurface>}
              renderItem={(row) => (
                <VButton
                  className={styles.providerButton}
                  contentLayout="plain"
                  variant={provider?.providerId === row.providerId ? "primary" : "ghost"}
                  onPress={() => onSelectProvider(row.providerId)}
                >
                  <span className={styles.providerIdentity}>
                    <strong className={styles.ellipsis} title={row.label}>{row.label || row.providerId}</strong>
                    <small className={styles.ellipsis} title={row.providerId}>{row.providerId}</small>
                  </span>
                  <VStatusChip tone={statusTone(row.status)} data-provider-status={row.status}>{row.status}</VStatusChip>
                </VButton>
              )}
            />
          </div>
        )}
        main={provider ? (
          <div className={styles.detailSurface} data-provider-status={provider.status}>
            <div className={styles.detailHeader}>
              <span className={styles.detailIdentity}>
                <strong title={provider.providerId}>{provider.label || provider.providerId}</strong>
                <small className={styles.muted}>{provider.providerId} · {provider.vendor || provider.serviceClass}</small>
              </span>
              <VActionGroup ariaLabel="Provider 操作" className={styles.actions}>
                <VButton
                  data-provider-action="discover"
                  icon={<RefreshCw size={14} />}
                  isDisabled={disabled}
                  onPress={() => onDiscover(provider.providerId)}
                >
                  {discoverBusy ? "发现中…" : "发现"}
                </VButton>
                <VButton
                  data-provider-action="credential"
                  aria-pressed={credentialActive}
                  variant={credentialActive ? "primary" : "ghost"}
                  isDisabled={disabled || provider.credentialState === "not_required"}
                  onPress={() => onEditCredential(provider.providerId)}
                >
                  设置 API Key
                </VButton>
                <VButton
                  data-provider-action="route"
                  aria-pressed={routeActive}
                  variant={routeActive ? "primary" : "ghost"}
                  icon={<Route size={14} />}
                  isDisabled={disabled}
                  onPress={() => onEditRoute(provider.providerId)}
                >
                  修改路由
                </VButton>
              </VActionGroup>
            </div>
            {visibleFeedback ? (
              <p
                className={visibleFeedback.phase === "error" ? styles.actionFeedbackError : styles.actionFeedback}
                data-feedback-phase={visibleFeedback.phase}
                role={visibleFeedback.phase === "error" ? "alert" : "status"}
                aria-live="polite"
              >
                {visibleFeedback.message}
              </p>
            ) : null}
            <VActionGroup ariaLabel="Provider 详情标签" className={styles.tabs}>
              {TABS.map((tab) => (
                <VButton
                  key={tab.id}
                  className={styles.tabButton}
                  variant={selectedTab === tab.id ? "primary" : "ghost"}
                  aria-pressed={selectedTab === tab.id}
                  onPress={() => onSelectTab(tab.id)}
                >
                  {tab.label}
                </VButton>
              ))}
            </VActionGroup>
            {selectedTab === "connection" ? <ConnectionTab provider={provider} /> : null}
            {selectedTab === "models" ? (
              <ProviderModelsTab
                provider={provider}
                disabled={disabled}
                modelQuery={modelQuery}
                modelFilter={modelFilter}
                liveReferenceCountByModelRef={liveReferenceCountByModelRef}
                onQueryChange={setModelQuery}
                onFilterChange={setModelFilter}
                onUnpin={onUnpin}
                onTestModel={onTestModel}
              />
            ) : null}
            {selectedTab === "protocols" ? <ProtocolsTab provider={provider} /> : null}
            {selectedTab === "diagnostics" ? <DiagnosticsTab provider={provider} disabled={disabled} onDiscover={onDiscover} /> : null}
            <div className={styles.mobileActionGroup}>
              <VButton
                variant="danger"
                icon={<Trash2 size={14} />}
                isDisabled={disabled || providerDeleteBlocked}
                title={providerDeleteBlocked ? "先清除 pinned ownership 与 live references，才能删除 Provider。" : "删除 Provider 草稿"}
                onPress={() => onDeleteProvider(provider.providerId)}
              >
                删除 Provider
              </VButton>
              {providerDeleteBlocked ? (
                <p className={styles.critical}><AlertTriangle size={14} className="inline" /> pinned: {provider.pinnedCount} · live refs: {providerLiveReferenceCount}，删除已禁用。</p>
              ) : null}
            </div>
          </div>
        ) : (
          <VStateSurface tone="empty" icon={<Database size={16} />} title="选择或创建 Provider">Provider 详情将在此处显示。</VStateSurface>
        )}
      />
    </VSurface>
  );
}
