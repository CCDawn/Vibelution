import { StrictMode, useEffect, useMemo, useState, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import {
  Activity,
  ArrowLeft,
  CheckCircle2,
  CircleAlert,
  Clock3,
  Database,
  Gauge,
  Info,
  LoaderCircle,
  Settings2,
  SlidersHorizontal,
  Wrench,
} from "lucide-react";

import {
  VButton,
  VNativeButton,
  VNativeSelect,
  VStateSurface,
  VStatusChip,
  VSurface,
  VTabs,
  VuiProvider,
  type VStatusTone,
} from "../components/vui";
import "./tailwind.css";
import "./base.css";
import "./tokens.css";
import "./vui-native-controls.css";
import "./vui-provider-theme.css";
import "./frontend-governance-preview.css";

type TabId = "settings" | "research" | "usage";
type PreviewState = "ready" | "loading" | "empty" | "blocked";
type MobileMode = "list" | "detail";

type Metric = {
  label: string;
  value: string;
  note?: string;
  tone?: "neutral" | "accent" | "success" | "warning" | "danger";
};

type GovernanceItem = {
  id: string;
  title: string;
  summary: string;
  status: string;
  tone: VStatusTone;
  icon: typeof Settings2;
  metrics: Metric[];
  recommendation: string;
  technical: Array<{ label: string; value: string }>;
  diagnostics: Array<{ label: string; value: string; tone?: VStatusTone }>;
};

const TAB_COPY: Record<TabId, { label: string; eyebrow: string; title: string; description: string }> = {
  settings: {
    label: "设置与服务",
    eyebrow: "治理设置",
    title: "让每个运行入口都有清楚的边界",
    description: "先看服务是否可用，再按需展开模型、参数和诊断信息。",
  },
  research: {
    label: "研究进度",
    eyebrow: "研究治理",
    title: "把研究阶段和当前阻塞放在同一条视线上",
    description: "摘要优先展示下一步；详细证据与阶段 ID 保持在展开区域。",
  },
  usage: {
    label: "用量",
    eyebrow: "资源治理",
    title: "用一眼能读懂的方式看清本周期用量",
    description: "先显示趋势和余量，原始计量参数只在需要排查时查看。",
  },
};

const ITEMS: Record<TabId, GovernanceItem[]> = {
  settings: [
    {
      id: "services",
      title: "服务与模型配置",
      summary: "查看当前连接、默认模型与访问边界。",
      status: "2 项需关注",
      tone: "warning",
      icon: Settings2,
      metrics: [
        { label: "服务", value: "4 个", note: "2 个可用" },
        { label: "默认模型", value: "已绑定", note: "运行前校验" },
        { label: "访问边界", value: "受控", note: "白名单" },
      ],
      recommendation: "先处理一个待确认的模型连接，再开始新的研究运行。",
      technical: [
        { label: "服务标识", value: "svc_local_inference_02" },
        { label: "模型标识", value: "model_frontend_governance_v3" },
        { label: "推理参数", value: "temperature=0.2 · max_tokens=4096" },
      ],
      diagnostics: [
        { label: "模型连接", value: "已通过最近一次模拟检查", tone: "success" },
        { label: "密钥来源", value: "未在预览中读取", tone: "neutral" },
        { label: "待确认项", value: "备用服务尚未完成绑定", tone: "warning" },
      ],
    },
    {
      id: "defaults",
      title: "工作台默认设置",
      summary: "统一页面密度、通知方式和权限基线。",
      status: "已同步",
      tone: "success",
      icon: SlidersHorizontal,
      metrics: [
        { label: "页面密度", value: "舒适", note: "可随时调整" },
        { label: "通知", value: "仅重要", note: "减少干扰" },
        { label: "权限基线", value: "受控", note: "需确认写入" },
      ],
      recommendation: "当前基线已足够支撑研究工作，无需额外调整。",
      technical: [
        { label: "配置版本", value: "workbench_defaults_r18" },
        { label: "布局记忆", value: "pane-layouts.v1" },
        { label: "通知策略", value: "important_events_only" },
      ],
      diagnostics: [
        { label: "读取状态", value: "最近一次同步成功", tone: "success" },
        { label: "覆盖项", value: "没有发现局部覆盖", tone: "success" },
      ],
    },
    {
      id: "diagnostics",
      title: "前端运行诊断",
      summary: "检查构建、资源和浏览器端状态。",
      status: "已完成",
      tone: "success",
      icon: Wrench,
      metrics: [
        { label: "构建", value: "通过", note: "最近一次" },
        { label: "资源", value: "正常", note: "无丢失" },
        { label: "浏览器端", value: "稳定", note: "无阻塞" },
      ],
      recommendation: "没有需要用户处理的诊断项，可以继续浏览其他治理信息。",
      technical: [
        { label: "构建标识", value: "frontend_audit_preview_20260909" },
        { label: "入口", value: "frontend-governance-preview.html" },
        { label: "资源策略", value: "vite_static_preview" },
      ],
      diagnostics: [
        { label: "样式加载", value: "通过", tone: "success" },
        { label: "控制台错误", value: "未发现", tone: "success" },
        { label: "真实 API", value: "预览未连接", tone: "neutral" },
      ],
    },
  ],
  research: [
    {
      id: "current",
      title: "挑战杯研究 · 文献筛选与研究假设评审",
      summary: "文献筛选已完成，等待确认下一阶段的研究假设。",
      status: "进行中",
      tone: "accent",
      icon: Activity,
      metrics: [
        { label: "阶段", value: "假设评审", note: "第 3 步 / 7 步" },
        { label: "完成度", value: "43%", note: "按阶段计算" },
        { label: "下一步", value: "确认假设", note: "等待研究负责人" },
      ],
      recommendation: "先检查候选假设和引用证据，再决定是否进入实验设计。",
      technical: [
        { label: "研究运行", value: "demo_research_run_20260909" },
        { label: "当前阶段", value: "hypothesis_review" },
        { label: "证据快照", value: "demo_evidence_snapshot_02" },
      ],
      diagnostics: [
        { label: "引用证据", value: "已关联文献", tone: "success" },
        { label: "实验阶段", value: "尚未开始", tone: "neutral" },
        { label: "评审状态", value: "等待评审材料意见", tone: "warning" },
      ],
    },
    {
      id: "evidence",
      title: "证据整理",
      summary: "整理文献摘要、引用来源与需要复核的研究结论。",
      status: "待审查",
      tone: "warning",
      icon: Database,
      metrics: [
        { label: "证据项", value: "18 条", note: "已收集" },
        { label: "待复核", value: "3 条", note: "需要人工复核" },
        { label: "来源", value: "本地快照", note: "未连接外部" },
      ],
      recommendation: "优先核对待复核结论的来源，完整标识可在技术信息中查看。",
      technical: [
        { label: "证据集合", value: "demo_literature_collection_v2" },
        { label: "快照数量", value: "18" },
        { label: "来源类型", value: "paper · dataset · benchmark" },
      ],
      diagnostics: [
        { label: "来源完整度", value: "引用链接已关联", tone: "success" },
        { label: "全文核验", value: "仍有 3 条待复核", tone: "neutral" },
      ],
    },
    {
      id: "next",
      title: "实验设计",
      summary: "依据已通过评审的假设，设计基线、对照组和评估指标。",
      status: "未开始",
      tone: "neutral",
      icon: Clock3,
      metrics: [
        { label: "实验基线", value: "待确认", note: "复用已登记方案" },
        { label: "对照组", value: "待确认", note: "控制单一变量" },
        { label: "评估指标", value: "4 项", note: "已列入计划" },
      ],
      recommendation: "先确认基线和评估指标，评审通过后再启动实验。",
      technical: [
        { label: "实验计划", value: "demo_experiment_plan_01" },
        { label: "实验阶段", value: "baseline · ablation" },
        { label: "评估指标", value: "accuracy · latency · cost · stability" },
      ],
      diagnostics: [
        { label: "实验运行", value: "尚未运行", tone: "warning" },
        { label: "评审材料", value: "已准备", tone: "success" },
      ],
    },
  ],
  usage: [
    {
      id: "period",
      title: "本周期用量",
      summary: "查看研究任务在当前周期内的资源消耗和剩余空间。",
      status: "使用平稳",
      tone: "success",
      icon: Gauge,
      metrics: [
        { label: "模型调用", value: "42%", note: "剩余充足", tone: "success" },
        { label: "工具调用", value: "31%", note: "低于预警线", tone: "success" },
        { label: "运行时间", value: "18%", note: "本周期" },
      ],
      recommendation: "当前用量不需要调整预算，继续观察研究阶段切换时的峰值。",
      technical: [
        { label: "周期标识", value: "usage_window_2026_09_01" },
        { label: "统计粒度", value: "project · agent · run" },
        { label: "预算规则", value: "soft_limit_80_hard_limit_100" },
      ],
      diagnostics: [
        { label: "数据更新时间", value: "预览快照 · 10:32", tone: "neutral" },
        { label: "异常峰值", value: "未发现", tone: "success" },
      ],
    },
    {
      id: "project",
      title: "研究项目预算",
      summary: "当前研究项目的调用额度、实际消耗和预警状态。",
      status: "接近预警线",
      tone: "warning",
      icon: Gauge,
      metrics: [
        { label: "已使用", value: "78%", note: "接近预警" , tone: "warning" },
        { label: "预计余量", value: "22%", note: "可完成本轮" , tone: "warning" },
        { label: "峰值来源", value: "模型调用", note: "需关注" },
      ],
      recommendation: "优先完成当前阶段，新增实验前检查剩余额度。",
      technical: [
        { label: "预算标识", value: "demo_research_budget" },
        { label: "已用 token", value: "156,800 / 200,000" },
        { label: "预警阈值", value: "160,000" },
      ],
      diagnostics: [
        { label: "预算状态", value: "未超限", tone: "success" },
        { label: "异常扣费", value: "未发现", tone: "success" },
        { label: "自动追加预算", value: "预览已关闭", tone: "neutral" },
      ],
    },
    {
      id: "local",
      title: "本地工具用量",
      summary: "查看构建、运行时长和本地预览占用的资源。",
      status: "数据不足",
      tone: "neutral",
      icon: Wrench,
      metrics: [
        { label: "工具调用", value: "—", note: "等待运行" },
        { label: "运行时长", value: "—", note: "等待运行" },
        { label: "本地缓存", value: "保留", note: "仅当前工作区" },
      ],
      recommendation: "当前尚无工具运行记录，完成一次调用后将显示统计。",
      technical: [
        { label: "工作区", value: "demo_research_project" },
        { label: "缓存目录", value: "project-cache" },
        { label: "收集模式", value: "local_only" },
      ],
      diagnostics: [
        { label: "真实采集", value: "尚未开始", tone: "warning" },
        { label: "预览数据", value: "模拟数据", tone: "neutral" },
      ],
    },
  ],
};

const SCENARIO_COPY: Record<PreviewState, string> = {
  ready: "正常摘要",
  loading: "模拟加载",
  empty: "模拟空状态",
  blocked: "模拟阻塞",
};

function toneForMetric(metric: Metric): VStatusTone {
  if (metric.tone) return metric.tone;
  return "neutral";
}

function StateSurface({
  state,
  item,
  onResetState,
  onShowBlockedDetails,
  showBlockedDetails,
}: {
  state: PreviewState;
  item: GovernanceItem;
  onResetState: () => void;
  onShowBlockedDetails: () => void;
  showBlockedDetails: boolean;
}) {
  if (state === "loading") {
    return (
      <VStateSurface
        className="fg-detail-state"
        tone="loading"
        title="正在读取治理摘要"
        icon={<LoaderCircle size={17} aria-hidden="true" />}
        skeletonLines={3}
        busy
      >
        这里会显示最近一次快照；当前只用于验证加载时的层级和占位。
      </VStateSurface>
    );
  }

  if (state === "empty") {
    return (
      <VStateSurface
        className="fg-detail-state"
        tone="empty"
        title="当前没有可展示的治理记录"
        icon={<Info size={17} aria-hidden="true" />}
        actions={<VButton variant="secondary" onClick={onResetState}>返回摘要</VButton>}
      >
        切换回正常摘要后，可以继续浏览「{item.title}」的模拟内容。
      </VStateSurface>
    );
  }

  if (state === "blocked") {
    return (
      <VStateSurface
        className="fg-detail-state"
        tone="unavailable"
        title="需要先处理一个阻塞项"
        icon={<CircleAlert size={17} aria-hidden="true" />}
        facts={[
          { key: "item", label: "当前项", value: item.title },
          { key: "next", label: "建议动作", value: "确认服务边界" },
        ]}
        actions={(
          <VButton variant="secondary" onClick={onShowBlockedDetails}>
            {showBlockedDetails ? "收起处理建议" : "查看处理建议"}
          </VButton>
        )}
      >
        <>
          模拟阻塞只强调下一步，不展开原始诊断文本；真实处理仍需要回到正式页面。
          {showBlockedDetails ? (
            <span className="fg-blocked-hint">建议先确认备用服务的连接边界，再重新运行检查。</span>
          ) : null}
        </>
      </VStateSurface>
    );
  }

  return null;
}

function GovernanceDetail({
  item,
  state,
  onResetState,
}: {
  item: GovernanceItem;
  state: PreviewState;
  onResetState: () => void;
}) {
  const Icon = item.icon;
  const [showBlockedDetails, setShowBlockedDetails] = useState(false);

  useEffect(() => {
    setShowBlockedDetails(false);
  }, [item.id, state]);

  const stateSurface = (
    <StateSurface
      state={state}
      item={item}
      onResetState={onResetState}
      onShowBlockedDetails={() => setShowBlockedDetails((current) => !current)}
      showBlockedDetails={showBlockedDetails}
    />
  );

  return (
    <VSurface as="section" tone="panel" elevation="panel" padding="none" className="fg-detail-panel">
      <div className="fg-detail-header">
        <div className="fg-detail-heading">
          <span className="fg-detail-icon" aria-hidden="true"><Icon size={17} /></span>
          <div>
            <p className="fg-overline">当前详情</p>
            <h2>{item.title}</h2>
            <p>{item.summary}</p>
          </div>
        </div>
        <VStatusChip tone={item.tone}>{item.status}</VStatusChip>
      </div>

      {state !== "ready" ? (
        <div className="fg-detail-body">{stateSurface}</div>
      ) : (
        <div className="fg-detail-body">
          <section className="fg-summary-block" aria-labelledby="summary-title">
            <div className="fg-section-heading">
              <div>
                <p className="fg-overline">摘要</p>
                <h3 id="summary-title">先看结论，再决定是否展开</h3>
              </div>
              <span className="fg-summary-note">模拟数据</span>
            </div>
            <div className="fg-metric-grid">
              {item.metrics.map((metric) => (
                <VSurface key={metric.label} tone="row" elevation="flat" padding="normal" className="fg-metric-card">
                  <span>{metric.label}</span>
                  <strong>{metric.value}</strong>
                  {metric.note ? <small>{metric.note}</small> : null}
                </VSurface>
              ))}
            </div>
            <div className="fg-recommendation">
              <CheckCircle2 size={16} aria-hidden="true" />
              <p><strong>建议</strong>{item.recommendation}</p>
            </div>
          </section>

          <details className="fg-disclosure">
            <summary>
              <span>技术信息</span>
              <small>技术 ID、参数和统计口径</small>
            </summary>
            <dl className="fg-detail-list">
              {item.technical.map((entry) => (
                <div key={entry.label}>
                  <dt>{entry.label}</dt>
                  <dd>{entry.value}</dd>
                </div>
              ))}
            </dl>
          </details>

          <details className="fg-disclosure">
            <summary>
              <span>诊断与来源</span>
              <small>只在需要排查时查看</small>
            </summary>
            <div className="fg-diagnostic-list">
              {item.diagnostics.map((entry) => (
                <div key={entry.label} className="fg-diagnostic-row">
                  <span>{entry.label}</span>
                  <VStatusChip tone={entry.tone ?? "neutral"}>{entry.value}</VStatusChip>
                </div>
              ))}
            </div>
          </details>
        </div>
      )}

      <footer className="fg-detail-footer">
        <span><Info size={14} aria-hidden="true" />本预览不会保存设置或连接真实服务。</span>
      </footer>
    </VSurface>
  );
}

function GovernancePreview() {
  const [activeTab, setActiveTab] = useState<TabId>("settings");
  const [state, setState] = useState<PreviewState>("ready");
  const [mobileMode, setMobileMode] = useState<MobileMode>("list");
  const [selectedIds, setSelectedIds] = useState<Record<TabId, string>>({
    settings: "services",
    research: "current",
    usage: "period",
  });

  const items = ITEMS[activeTab];
  const selectedId = selectedIds[activeTab];
  const selectedItem = useMemo(
    () => items.find((item) => item.id === selectedId) ?? items[0],
    [items, selectedId],
  );

  useEffect(() => {
    setMobileMode("list");
  }, [activeTab]);

  const selectItem = (id: string) => {
    setSelectedIds((current) => ({ ...current, [activeTab]: id }));
    setMobileMode("detail");
  };

  const tabItems = (Object.keys(TAB_COPY) as TabId[]).map((id) => ({
    id,
    label: TAB_COPY[id].label,
  }));

  return (
    <VuiProvider>
      <div className="fg-preview" data-mobile-mode={mobileMode}>
        <header className="fg-topbar">
          <div className="fg-brand">
            <span className="fg-brand-mark" aria-hidden="true">V</span>
            <div>
              <strong>Vibelution</strong>
              <span>前端治理预览</span>
            </div>
          </div>
          <div className="fg-topbar-meta">
            <VStatusChip tone="success">模拟数据</VStatusChip>
            <span className="fg-topbar-divider" aria-hidden="true" />
            <span>仅用于交互确认</span>
          </div>
        </header>

        <main className="fg-main">
          <header className="fg-page-header">
            <div>
              <p className="fg-overline">前端治理</p>
              <h1>{TAB_COPY[activeTab].title}</h1>
              <p>{TAB_COPY[activeTab].description}</p>
            </div>
            <div className="fg-page-badge">
              <span>当前场景</span>
              <strong>{SCENARIO_COPY[state]}</strong>
            </div>
          </header>

          <VSurface tone="toolbar" elevation="flat" padding="compact" className="fg-control-surface">
            <VTabs
              items={tabItems}
              value={activeTab}
              onValueChange={(value) => setActiveTab(value as TabId)}
              aria-label="前端治理分区"
              listClassName="fg-tab-list"
              triggerClassName="fg-tab-trigger"
            />
            <div className="fg-scenario-control">
              <label htmlFor="fg-scenario">状态预览</label>
              <VNativeSelect
                id="fg-scenario"
                value={state}
                onChange={(event) => setState(event.target.value as PreviewState)}
                aria-label="切换模拟状态"
              >
                {(Object.keys(SCENARIO_COPY) as PreviewState[]).map((id) => (
                  <option key={id} value={id}>{SCENARIO_COPY[id]}</option>
                ))}
              </VNativeSelect>
            </div>
          </VSurface>

          <div className="fg-workspace" aria-live="polite">
            <VSurface as="aside" tone="rail" elevation="panel" padding="none" className="fg-list-panel">
              <div className="fg-list-header">
                <div>
                  <p className="fg-overline">{TAB_COPY[activeTab].eyebrow}</p>
                  <h2>{TAB_COPY[activeTab].label}</h2>
                </div>
                <span className="fg-list-count">{items.length} 项</span>
              </div>
              <div className="fg-list-body">
                {state === "empty" ? (
                  <VStateSurface
                    className="fg-list-state"
                    tone="empty"
                    title="暂无治理项目"
                    icon={<Info size={16} aria-hidden="true" />}
                  >
                    这是空状态示例；切换回正常摘要可继续浏览。
                  </VStateSurface>
                ) : state === "loading" ? (
                  <VStateSurface
                    className="fg-list-state"
                    tone="loading"
                    title="正在读取项目列表"
                    icon={<LoaderCircle size={16} aria-hidden="true" />}
                    skeletonLines={2}
                    busy
                  />
                ) : (
                  items.map((item) => {
                    const Icon = item.icon;
                    const selected = item.id === selectedId;
                    return (
                      <VNativeButton
                        key={item.id}
                        className={`fg-list-item${selected ? " is-selected" : ""}`}
                        aria-current={selected ? "true" : undefined}
                        onClick={() => selectItem(item.id)}
                      >
                        <span className="fg-list-icon" aria-hidden="true"><Icon size={16} /></span>
                        <span className="fg-list-copy">
                          <span className="fg-list-item-topline">
                            <strong>{item.title}</strong>
                            <VStatusChip tone={item.tone}>{item.status}</VStatusChip>
                          </span>
                          <small>{item.summary}</small>
                        </span>
                      </VNativeButton>
                    );
                  })
                )}
              </div>
            </VSurface>

            <div className="fg-detail-wrap">
              <div className="fg-mobile-detail-nav">
                <VButton
                  variant="ghost"
                  icon={<ArrowLeft size={15} aria-hidden="true" />}
                  onClick={() => setMobileMode("list")}
                >
                  返回列表
                </VButton>
              </div>
              <GovernanceDetail
                item={selectedItem}
                state={state}
                onResetState={() => setState("ready")}
              />
            </div>
          </div>

          <p className="fg-page-note">模拟数据 · 用于确认信息层级、响应式布局和状态切换；正式页面仍需浏览器验收。</p>
        </main>
      </div>
    </VuiProvider>
  );
}

const root = document.getElementById("root");

if (root) {
  createRoot(root).render(
    <StrictMode>
      <GovernancePreview />
    </StrictMode>,
  );
}
