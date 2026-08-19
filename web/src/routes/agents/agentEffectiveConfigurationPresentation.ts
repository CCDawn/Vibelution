import type {
  AgentEffectiveConfigurationField,
  AgentMemoryPolicyOption,
  AgentModelChoice,
  AgentToolPolicyOption,
  AgentToolPolicySource,
  PromptTemplate,
} from "../../api/types";

export type AgentFocusedEffectiveResources = {
  dialogueModel?: AgentModelChoice | null;
  promptTemplate?: PromptTemplate | null;
  toolPolicy?: AgentToolPolicyOption | null;
  toolPolicySource?: AgentToolPolicySource | null;
  memoryPolicy?: AgentMemoryPolicyOption | null;
};

export type FocusedEffectiveValueView = {
  primary: string;
  secondary?: string;
  rawId?: string;
};

function presentationCopy(lang: "zh" | "en") {
  return lang === "zh"
    ? { configured: "已配置", enabled: "已启用", disabled: "未启用", items: "项" }
    : { configured: "Configured", enabled: "Enabled", disabled: "Disabled", items: "items" };
}

function uniqueParts(parts: Array<string | undefined>): string[] {
  return [...new Set(parts.map((part) => String(part || "").trim()).filter(Boolean))];
}

function formatTokenCount(value: unknown, lang: "zh" | "en"): string {
  const count = Number(value || 0);
  if (!Number.isFinite(count) || count <= 0) return "";
  if (lang === "zh" && count >= 10_000) {
    return `${new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 1 }).format(count / 10_000)} 万 tokens`;
  }
  if (lang === "en" && count >= 1_000_000) {
    return `${new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 }).format(count / 1_000_000)}M tokens`;
  }
  if (lang === "en" && count >= 1_000) {
    return `${new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 }).format(count / 1_000)}K tokens`;
  }
  return `${count.toLocaleString(lang === "zh" ? "zh-CN" : "en-US")} tokens`;
}

function sourceTypeLabel(value: string, lang: "zh" | "en"): string {
  const labels = lang === "zh"
    ? { workspace_file: "工作区文件", inline_record: "内嵌配置", empty: "空模板" }
    : { workspace_file: "Workspace file", inline_record: "Inline config", empty: "Empty template" };
  return labels[value as keyof typeof labels] || value;
}

function promptCategoryLabel(value: string, lang: "zh" | "en"): string {
  const labels = lang === "zh"
    ? {
        general: "通用模板",
        chat: "对话模板",
        research: "科研模板",
        self_evolution: "自进化模板",
        supervised_evolution: "监督进化模板",
      }
    : {
        general: "General template",
        chat: "Chat template",
        research: "Research template",
        self_evolution: "Self-evolution template",
        supervised_evolution: "Supervised evolution template",
      };
  return labels[value as keyof typeof labels] || value;
}

function policyAccessLabel(value: string, kind: "network" | "mutation", lang: "zh" | "en"): string {
  const networkLabels = lang === "zh"
    ? { inherit: "继承网络规则", none: "禁止联网", controlled: "受控网络", unrestricted: "不受限网络" }
    : { inherit: "Inherited network rules", none: "No network", controlled: "Controlled network", unrestricted: "Unrestricted network" };
  const mutationLabels = lang === "zh"
    ? { inherit: "继承写入规则", none: "禁止写入/命令", restricted: "受限写入", controlled: "受控写入", unrestricted: "完全写入" }
    : { inherit: "Inherited write rules", none: "No writes or commands", restricted: "Restricted writes", controlled: "Controlled writes", unrestricted: "Unrestricted writes" };
  const labels = kind === "network" ? networkLabels : mutationLabels;
  return labels[value as keyof typeof labels] || value;
}

export function effectiveConfigurationSourceLabel(
  kind: string,
  lang: "zh" | "en",
  fallbackLabel = "",
): string {
  const labels = lang === "zh"
    ? {
        agent: "此 Agent",
        mode_default: "模式默认",
        global: "全局默认",
        shared_policy: "共享策略",
        system: "系统固定",
      }
    : {
        agent: "This Agent",
        mode_default: "Mode default",
        global: "Global default",
        shared_policy: "Shared policy",
        system: "System fixed",
      };
  return labels[kind as keyof typeof labels] || fallbackLabel || kind || "-";
}

export function focusedEffectiveValue(
  field: Pick<AgentEffectiveConfigurationField, "key" | "effectiveValue">,
  lang: "zh" | "en",
  resources: AgentFocusedEffectiveResources = {},
): FocusedEffectiveValueView {
  const copy = presentationCopy(lang);
  const value = field.effectiveValue;
  const rawId = typeof value === "string" ? value.trim() : "";
  const idFallback = lang === "zh" ? "仅有内部标识" : "Internal identifier only";

  if (field.key === "dialogueModel") {
    const model = resources.dialogueModel;
    if (!model) return { primary: rawId || "-", secondary: rawId ? idFallback : undefined };
    const primary = String(model.label || model.model || model.upstreamId || rawId || "-").trim();
    const normalizedProviderLabel = String(model.providerLabel || "").trim().toLocaleLowerCase();
    const normalizedProviderKind = String(model.providerKind || "").trim().toLocaleLowerCase();
    const secondary = uniqueParts([
      model.providerLabel,
      normalizedProviderKind && !normalizedProviderLabel.includes(normalizedProviderKind)
        ? model.providerKind
        : "",
      model.contextWindow
        ? `${lang === "zh" ? "上下文" : "Context"} ${formatTokenCount(model.contextWindow, lang)}`
        : "",
    ]).join(" · ");
    return { primary, secondary: secondary || undefined, rawId: rawId && rawId !== primary ? rawId : undefined };
  }

  if (field.key === "promptTemplate") {
    const template = resources.promptTemplate;
    if (!template) return { primary: rawId || "-", secondary: rawId ? idFallback : undefined };
    const name = String(template.name || "").trim();
    const primary = name || rawId || "-";
    const secondary = uniqueParts([
      promptCategoryLabel(String(template.category || ""), lang),
      sourceTypeLabel(String(template.sourceType || ""), lang),
    ]).join(" · ");
    return {
      primary,
      secondary: secondary || (!name && rawId ? idFallback : undefined),
      rawId: rawId && rawId !== primary ? rawId : undefined,
    };
  }

  if (field.key === "toolPolicy") {
    const policy = resources.toolPolicy;
    if (!policy) return { primary: rawId || "-", secondary: rawId ? idFallback : undefined };
    const allowed = Number(policy.allowedToolCount || 0);
    const primary = lang === "zh"
      ? (allowed ? `${allowed} 个工具可用` : "未开放工具")
      : (allowed ? `${allowed} tools available` : "No tools available");
    const mutatingCount = Number(resources.toolPolicySource?.mutatingToolCount || 0);
    const secondary = uniqueParts([
      mutatingCount > 0
        ? (lang === "zh" ? `${mutatingCount} 个可写/命令工具` : `${mutatingCount} write/command tools`)
        : policy.mutationAccess ? policyAccessLabel(policy.mutationAccess, "mutation", lang) : "",
      policy.networkAccess ? policyAccessLabel(policy.networkAccess, "network", lang) : "",
      Number(policy.maxCallsPerTurn || 0) > 0
        ? (lang === "zh" ? `每轮最多 ${policy.maxCallsPerTurn} 次` : `Up to ${policy.maxCallsPerTurn} calls/turn`)
        : (lang === "zh" ? "每轮不限次数" : "No per-turn limit"),
    ]).join(" · ");
    return { primary, secondary, rawId: rawId || policy.policyId };
  }

  if (field.key === "memoryPolicy") {
    const policy = resources.memoryPolicy;
    if (!policy) return { primary: rawId || "-", secondary: rawId ? idFallback : undefined };
    const hasPrivateMemory = Boolean(String(policy.privateMemoryRoot || "").trim());
    const primary = lang === "zh"
      ? (hasPrivateMemory ? "私有记忆已配置" : "未配置私有记忆")
      : (hasPrivateMemory ? "Private memory configured" : "No private memory");
    const sharedCount = policy.readSharedGroupCount + policy.writeSharedGroupCount;
    const knowledgeCount = policy.readKnowledgeBaseCount
      + policy.proposeKnowledgeBaseCount
      + policy.reviewKnowledgeBaseCount;
    const secondary = uniqueParts([
      sharedCount > 0
        ? (lang === "zh"
            ? `共享组：读 ${policy.readSharedGroupCount} / 写 ${policy.writeSharedGroupCount}`
            : `Shared groups: read ${policy.readSharedGroupCount} / write ${policy.writeSharedGroupCount}`)
        : "",
      knowledgeCount > 0
        ? (lang === "zh"
            ? `知识库：读 ${policy.readKnowledgeBaseCount} / 提议 ${policy.proposeKnowledgeBaseCount} / 评审 ${policy.reviewKnowledgeBaseCount}`
            : `Knowledge bases: read ${policy.readKnowledgeBaseCount} / propose ${policy.proposeKnowledgeBaseCount} / review ${policy.reviewKnowledgeBaseCount}`)
        : "",
      policy.hasInboxPath ? (lang === "zh" ? "含收件箱" : "Inbox enabled") : "",
      sharedCount === 0 && knowledgeCount === 0 && hasPrivateMemory
        ? (lang === "zh" ? "仅私有记忆" : "Private memory only")
        : "",
    ]).join(" · ");
    return { primary, secondary: secondary || undefined, rawId: rawId || policy.policyId };
  }

  if (value === null || value === undefined || value === "") return { primary: "-" };
  if (typeof value === "string" || typeof value === "number") return { primary: String(value) };
  if (typeof value === "boolean") return { primary: value ? copy.enabled : copy.disabled };
  if (Array.isArray(value)) {
    return { primary: value.length ? `${value.length} ${copy.items}` : "-" };
  }
  if (typeof value !== "object") return { primary: copy.configured };
  const record = value as Record<string, unknown>;
  if (field.key === "contextCompression") {
    if (record.enabled === false) return { primary: copy.disabled };
    const mode = String(record.mode || "inherit");
    const limit = Number(record.compressionTriggerTokenLimit
      || record.effectiveTokenLimit
      || record.maxTokenLimit
      || 0);
    const windowLimit = Number(record.modelContextWindowLimit || record.contextWindowLimit || 0);
    const primary = limit > 0
      ? `${formatTokenCount(limit, lang)} ${lang === "zh" ? "后压缩" : "before compression"}`
      : copy.enabled;
    const secondary = uniqueParts([
      mode === "custom"
        ? (lang === "zh" ? "自定义阈值" : "Custom threshold")
        : (lang === "zh" ? "跟随全局" : "Inherits global policy"),
      windowLimit > 0
        ? `${lang === "zh" ? "模型窗口" : "Model window"} ${formatTokenCount(windowLimit, lang)}`
        : "",
    ]).join(" · ");
    return { primary, secondary };
  }
  if (field.key === "delegation") {
    if (record.allowSubagents !== true) return { primary: copy.disabled };
    const concurrency = Number(record.maxConcurrent || 0);
    const depth = Number(record.maxDepth || 0);
    const primary = concurrency > 0
      ? (lang === "zh" ? `最多 ${concurrency} 个并发` : `Up to ${concurrency} concurrent`)
      : copy.enabled;
    const contextModes = Array.isArray(record.allowedContextModes)
      ? record.allowedContextModes.map((mode) => {
          if (mode === "isolated") return lang === "zh" ? "隔离上下文" : "Isolated context";
          if (mode === "fork") return lang === "zh" ? "分叉上下文" : "Forked context";
          return String(mode);
        }).join(" / ")
      : "";
    const secondary = uniqueParts([
      depth > 0 ? (lang === "zh" ? `最大深度 ${depth}` : `Max depth ${depth}`) : "",
      record.allowWakeMessages === true ? (lang === "zh" ? "允许唤醒消息" : "Wake messages allowed") : "",
      contextModes,
    ]).join(" · ");
    return { primary, secondary: secondary || undefined };
  }
  if (field.key === "supervision") {
    if (record.supervisionEnabled !== true) return { primary: copy.disabled };
    const reviewMode = String(record.reviewMode || "advisory");
    const primaryLabels = lang === "zh"
      ? { advisory: "建议评审，不阻断", required: "必须评审，通过后继续", disabled: "不要求评审" }
      : { advisory: "Advisory review, non-blocking", required: "Review required before continuing", disabled: "Review not required" };
    const evidenceLevel = String(record.evidenceLevel || "standard");
    const evidenceLabels = lang === "zh"
      ? { light: "轻量证据", standard: "标准证据", strict: "严格证据" }
      : { light: "Light evidence", standard: "Standard evidence", strict: "Strict evidence" };
    return {
      primary: primaryLabels[reviewMode as keyof typeof primaryLabels] || reviewMode,
      secondary: evidenceLabels[evidenceLevel as keyof typeof evidenceLabels] || evidenceLevel,
    };
  }
  const conciseValue = record.modelId
    || record.modelRef
    || record.promptTemplateId
    || record.policyId
    || record.id;
  return conciseValue ? { primary: String(conciseValue) } : { primary: copy.configured };
}
