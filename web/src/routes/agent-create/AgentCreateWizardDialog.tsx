import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, MessageSquare, Settings2, X } from "lucide-react";
import { type RefObject, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { fetchJson } from "../../api/client";
import { queryKeys } from "../../api/queryKeys";
import {
  type AgentConfigWorkspace,
  type AgentConfigWorkspaceAgent,
  type ToolRegistryPayload,
} from "../../api/types";
import { VButton } from "../../components/vui";
import { useShellI18n } from "../../i18n/useShellI18n";
import { AgentCreatePanel, type AgentCreatePanelCopy } from "../AgentCreatePanel";
import { createChatWorkspaceCache } from "../chatWorkspaceCache";
import {
  buildAgentModelChoices,
  createAgentPayload,
  createAgentPresets,
  createDraftFromWorkspace,
  createDraftReady,
  createToolBundleSummary,
  dialogueModelId,
  isWorkSessionCreateDraft,
  normalizeCreateDraftForWorkspace,
  toolBundleIdsForModeChange,
  toolBundleMeta,
  type AgentCreateDraft,
  withDialogueModel,
} from "./agentCreateContract";
import styles from "./AgentCreateWizardDialog.styles";

type AgentCreateWizardDialogProps = {
  open: boolean;
  /** The invoking control receives focus again when this modal closes. */
  triggerRef?: RefObject<HTMLElement | null>;
  triggerId?: string;
  onClose: () => void;
  onCreated?: (agent: AgentConfigWorkspaceAgent) => void;
  onStartConversation?: (agent: AgentConfigWorkspaceAgent) => Promise<boolean> | boolean | void;
  onOpenAdvancedConfig?: (agent: AgentConfigWorkspaceAgent) => void;
};

function dialogCopy(lang: "zh" | "en"): AgentCreatePanelCopy {
  return lang === "zh" ? {
    createAgent: "创建 Agent",
    createAgentTitle: "创建会话 Agent",
    createAgentHint: "默认值来自当前模型库、提示词模板和工具包。创建后仍可继续调整。",
    createAgentName: "功能名",
    createAgentNamePlaceholder: "例如：项目开发 Agent",
    createAgentRole: "角色键",
    createAgentRolePlaceholder: "必填，例如 research_reviewer",
    createAgentPersonaSummary: "人物摘要",
    createAgentPersonaPlaceholder: "例如：冷静、细致，负责把结论拆成可验证证据。",
    createAgentTaskMission: "任务使命",
    createAgentTaskMissionPlaceholder: "例如：复核科研结论，指出证据缺口并给出下一步建议。",
    createAgentAllowedToolsPlaceholder: "例如：agent_message_tool, web_search_tool",
    createAgentToolBundles: "工具包",
    createAgentToolBundlesHint: "选择适合这个 Agent 的能力包；创建后仍可在工具能力中细调单个工具。",
    createAgentToolBundlePreview: "创建后工具能力",
    createAgentToolBundleEmpty: "还没有选择工具包。",
    cancelCreate: "取消",
    creatingAgent: "正在创建…",
    modeMembership: "使用位置",
    model: "模型",
    prompt: "提示词",
  } : {
    createAgent: "Create Agent",
    createAgentTitle: "Create chat Agent",
    createAgentHint: "Defaults come from the current model library, prompt templates, and tool packages. You can fine-tune this Agent after creation.",
    createAgentName: "Name",
    createAgentNamePlaceholder: "e.g. Project development Agent",
    createAgentRole: "Role key",
    createAgentRolePlaceholder: "Required, e.g. research_reviewer",
    createAgentPersonaSummary: "Persona summary",
    createAgentPersonaPlaceholder: "e.g. Calm, detailed, and evidence-first.",
    createAgentTaskMission: "Task mission",
    createAgentTaskMissionPlaceholder: "e.g. Review research conclusions and identify evidence gaps.",
    createAgentAllowedToolsPlaceholder: "e.g. agent_message_tool, web_search_tool",
    createAgentToolBundles: "Tool packages",
    createAgentToolBundlesHint: "Choose capability packages for this Agent. You can still tune individual tools after creation.",
    createAgentToolBundlePreview: "Tool permissions after creation",
    createAgentToolBundleEmpty: "No tool package selected.",
    cancelCreate: "Cancel",
    creatingAgent: "Creating…",
    modeMembership: "Use in",
    model: "Model",
    prompt: "Prompt",
  };
}

function focusableElements(container: HTMLElement | null) {
  if (!container) return [];
  return Array.from(container.querySelectorAll<HTMLElement>(
    'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
  )).filter((element) => !element.hidden && element.offsetParent !== null);
}

export function AgentCreateWizardDialog({
  open,
  triggerRef,
  triggerId,
  onClose,
  onCreated,
  onStartConversation,
  onOpenAdvancedConfig,
}: AgentCreateWizardDialogProps) {
  const { lang } = useShellI18n();
  const queryClient = useQueryClient();
  const chatWorkspaceCache = useMemo(() => createChatWorkspaceCache(queryClient), [queryClient]);
  const copy = useMemo(() => dialogCopy(lang), [lang]);
  const dialogRef = useRef<HTMLDivElement>(null);
  const returnFocusRef = useRef<HTMLElement | null>(null);
  const [draft, setDraft] = useState<AgentCreateDraft>(() => createDraftFromWorkspace(undefined, [], lang));
  const [draftDirty, setDraftDirty] = useState(false);
  const [discardConfirmOpen, setDiscardConfirmOpen] = useState(false);
  const [createdAgent, setCreatedAgent] = useState<AgentConfigWorkspaceAgent | null>(null);
  const [startConversationError, setStartConversationError] = useState("");
  const [startingConversation, setStartingConversation] = useState(false);
  const [instanceKey, setInstanceKey] = useState(0);

  const workspaceQuery = useQuery({
    queryKey: queryKeys.agentConfigWorkspace(),
    queryFn: () => fetchJson<AgentConfigWorkspace>("/api/agents/config-workspace?includeRuntime=false"),
    enabled: open,
    staleTime: 10_000,
  });
  const toolsQuery = useQuery({
    queryKey: queryKeys.tools(),
    queryFn: () => fetchJson<ToolRegistryPayload>("/api/tools"),
    enabled: open,
    staleTime: 10_000,
  });
  const toolBundles = toolsQuery.data?.toolBundles ?? [];
  const modelChoices = useMemo(() => buildAgentModelChoices(workspaceQuery.data?.agentModelChoices ?? []), [workspaceQuery.data?.agentModelChoices]);
  const promptTemplateOptions = useMemo(
    () => (workspaceQuery.data?.promptTemplates ?? []).map((template) => ({
      value: template.promptTemplateId || template.templateId || "",
      label: template.name || template.promptTemplateId || template.templateId || "-",
    })).filter((template) => template.value),
    [workspaceQuery.data?.promptTemplates],
  );
  const primaryModeOptions = useMemo(() => lang === "zh"
    ? [{ value: "chat", label: "会话" }, { value: "research", label: "研究" }, { value: "general", label: "通用" }]
    : [{ value: "chat", label: "Chat" }, { value: "research", label: "Research" }, { value: "general", label: "General" }], [lang]);
  const presets = useMemo(() => createAgentPresets(workspaceQuery.data, toolBundles, lang), [lang, toolBundles, workspaceQuery.data]);
  const toolBundleSummary = useMemo(() => createToolBundleSummary(draft.selectedToolBundleIds, toolBundles, lang), [draft.selectedToolBundleIds, lang, toolBundles]);
  const selectedModelId = dialogueModelId(draft.llmBindings);
  const canCreate = createDraftReady(draft, toolBundles);
  const loadingOptions = workspaceQuery.isPending || toolsQuery.isPending;
  const optionsError = workspaceQuery.isError || toolsQuery.isError
    ? (lang === "zh" ? "部分创建选项加载失败。可以重试；已填写内容会保留。" : "Some creation options failed to load. Retry is available and your draft is preserved.")
    : "";

  useEffect(() => {
    if (!open) return;
    returnFocusRef.current = triggerRef?.current
      ?? (document.activeElement instanceof HTMLElement ? document.activeElement : null);
    setDraft(createDraftFromWorkspace(undefined, [], lang));
    setDraftDirty(false);
    setDiscardConfirmOpen(false);
    setCreatedAgent(null);
    setStartConversationError("");
    setStartingConversation(false);
    setInstanceKey((current) => current + 1);
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    requestAnimationFrame(() => {
      const initialFocus = dialogRef.current?.querySelector<HTMLElement>("[autofocus]")
        ?? focusableElements(dialogRef.current)[0];
      initialFocus?.focus();
    });
    return () => {
      document.body.style.overflow = previousOverflow;
      const fallbackFocusTarget = returnFocusRef.current;
      // The portal is removed in the same commit as this cleanup. Defer so the
      // browser does not subsequently move focus from the removed close button
      // back to <body>.
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          const focusTarget = triggerId ? document.getElementById(triggerId) : fallbackFocusTarget;
          if (focusTarget instanceof HTMLElement && focusTarget.isConnected) {
            focusTarget.focus();
          }
        });
      });
    };
  }, [lang, open, triggerId, triggerRef]);

  useEffect(() => {
    if (!open || draftDirty || (!workspaceQuery.data && !toolBundles.length)) return;
    setDraft((current) => {
      const normalized = normalizeCreateDraftForWorkspace(current, workspaceQuery.data, toolBundles, lang);
      if (normalized.selectedToolBundleIds.length || !toolBundles.length) return normalized;
      return {
        ...normalized,
        selectedToolBundleIds: createDraftFromWorkspace(workspaceQuery.data, toolBundles, lang).selectedToolBundleIds,
      };
    });
  }, [draftDirty, lang, open, toolBundles, workspaceQuery.data]);

  const createMutation = useMutation({
    mutationFn: (nextDraft: AgentCreateDraft) => fetchJson<AgentConfigWorkspaceAgent>("/api/agents", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(createAgentPayload(nextDraft, toolBundles)),
    }),
    onSuccess: (agent) => {
      setCreatedAgent(agent);
      setStartConversationError("");
      onCreated?.(agent);
      void Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.agentSummary(true) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.agentConfigWorkspace() }),
      ]);
      void chatWorkspaceCache.afterAgentWorkspaceChanged();
    },
  });

  const closeNow = () => {
    setDiscardConfirmOpen(false);
    onClose();
  };
  const requestClose = () => {
    if (createMutation.isPending || startingConversation) return;
    if (!createdAgent && draftDirty) {
      setDiscardConfirmOpen(true);
      return;
    }
    closeNow();
  };

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        requestClose();
        return;
      }
      if (event.key !== "Tab") return;
      const elements = focusableElements(dialogRef.current);
      if (!elements.length) return;
      const first = elements[0];
      const last = elements[elements.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  });

  if (!open || typeof document === "undefined") return null;

  const updateDraft = (patch: Partial<AgentCreateDraft>) => {
    setDraft((current) => ({ ...current, ...patch }));
    setDraftDirty(true);
  };
  const applyPreset = (nextDraft: AgentCreateDraft) => {
    setDraft(nextDraft);
    setDraftDirty(true);
  };
  const toggleToolBundle = (bundleId: string, selected: boolean) => {
    setDraft((current) => {
      const next = new Set(current.selectedToolBundleIds);
      if (selected) next.add(bundleId);
      else next.delete(bundleId);
      return { ...current, selectedToolBundleIds: Array.from(next).sort() };
    });
    setDraftDirty(true);
  };
  const startConversation = async () => {
    if (!createdAgent || !onStartConversation || startingConversation) return;
    setStartingConversation(true);
    setStartConversationError("");
    try {
      const started = await onStartConversation(createdAgent);
      if (started !== false) closeNow();
      else setStartConversationError(lang === "zh" ? "会话创建失败，Agent 已保留。可以重试。" : "The Agent was created, but the session could not be created. Try again.");
    } catch {
      setStartConversationError(lang === "zh" ? "会话创建失败，Agent 已保留。可以重试。" : "The Agent was created, but the session could not be created. Try again.");
    } finally {
      setStartingConversation(false);
    }
  };
  const headingId = "agent-create-wizard-title";
  const descriptionId = "agent-create-wizard-description";

  return createPortal(
    <div className={styles.overlay} role="presentation" onMouseDown={requestClose}>
      <div
        ref={dialogRef}
        className={styles.dialog}
        role="dialog"
        aria-modal="true"
        aria-labelledby={headingId}
        aria-describedby={descriptionId}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className={styles.header}>
          <div className={styles.heading}>
            <span className={styles.eyebrow}>{lang === "zh" ? "会话工作台" : "Chat workspace"}</span>
            <h2 id={headingId}>{createdAgent ? (lang === "zh" ? "Agent 已创建" : "Agent created") : copy.createAgentTitle}</h2>
            <p id={descriptionId}>{createdAgent
              ? (lang === "zh" ? "现在即可进入与新 Agent 的对话，或继续完善高级配置。" : "Start a conversation now or continue with advanced configuration.")
              : (lang === "zh" ? "3 步完成；当前对话会保留在背景中。" : "Finish in three steps; your current conversation stays in place.")}</p>
          </div>
          <VButton type="button" variant="ghost" isIconOnly aria-label={lang === "zh" ? "关闭创建向导" : "Close create wizard"} onPress={requestClose}>
            <X size={17} aria-hidden="true" />
          </VButton>
        </header>

        <div className={styles.body}>
          {discardConfirmOpen ? (
            <section className={styles.confirmation} aria-live="polite">
              <strong>{lang === "zh" ? "放弃本次填写？" : "Discard this draft?"}</strong>
              <p>{lang === "zh" ? "尚未创建 Agent，关闭后本次填写不会保留。" : "No Agent has been created. Closing discards this draft."}</p>
              <div className={styles.confirmationActions}>
                <VButton type="button" variant="secondary" onPress={() => setDiscardConfirmOpen(false)}>{lang === "zh" ? "继续填写" : "Keep editing"}</VButton>
                <VButton type="button" variant="danger" onPress={closeNow}>{lang === "zh" ? "放弃并关闭" : "Discard"}</VButton>
              </div>
            </section>
          ) : createdAgent ? (
            <section className={styles.success} aria-live="polite">
              <CheckCircle2 size={28} aria-hidden="true" />
              <div>
                <strong>{lang === "zh" ? `已创建 ${createdAgent.displayName}` : `Created ${createdAgent.displayName}`}</strong>
                <p>{lang === "zh" ? "Agent 已加入当前工作台。" : "The Agent is now available in this workspace."}</p>
              </div>
              {startConversationError ? <p className={styles.error}>{startConversationError}</p> : null}
              <div className={styles.successActions}>
                {onStartConversation ? <VButton type="button" variant="primary" icon={<MessageSquare size={15} />} isDisabled={startingConversation} onPress={() => { void startConversation(); }}>{startingConversation ? (lang === "zh" ? "正在创建会话…" : "Creating session…") : (lang === "zh" ? "开始对话" : "Start conversation")}</VButton> : null}
                {onOpenAdvancedConfig ? <VButton type="button" variant="secondary" icon={<Settings2 size={15} />} isDisabled={startingConversation} onPress={() => onOpenAdvancedConfig(createdAgent)}>{lang === "zh" ? "继续高级配置" : "Advanced configuration"}</VButton> : null}
                <VButton type="button" variant="secondary" isDisabled={startingConversation} onPress={closeNow}>{lang === "zh" ? "完成" : "Done"}</VButton>
              </div>
            </section>
          ) : (
            <AgentCreatePanel
              key={instanceKey}
              copy={copy}
              draft={draft}
              selectedModelId={selectedModelId}
              isWorkSession={isWorkSessionCreateDraft(draft)}
              canCreate={canCreate}
              pending={createMutation.isPending}
              loadingOptions={loadingOptions}
              optionsError={optionsError}
              notice={createMutation.isError ? { tone: "error", text: createMutation.error instanceof Error ? createMutation.error.message : String(createMutation.error) } : null}
              modelChoices={modelChoices}
              primaryModeOptions={primaryModeOptions}
              promptTemplateOptions={promptTemplateOptions}
              toolBundles={toolBundles}
              toolBundleSummary={toolBundleSummary}
              toolBundleMeta={(bundle) => toolBundleMeta(bundle, lang)}
              presets={presets}
              lang={lang}
              onDraftChange={updateDraft}
              onApplyPreset={applyPreset}
              onModelChange={(modelId) => updateDraft({ llmBindings: withDialogueModel(draft.llmBindings, modelId) })}
              onPrimaryModeChange={(primaryMode) => updateDraft({ primaryMode, selectedToolBundleIds: toolBundleIdsForModeChange(draft, primaryMode, toolBundles) })}
              onToolBundleToggle={toggleToolBundle}
              onCancel={requestClose}
              onCreate={() => createMutation.mutate(draft)}
            />
          )}
        </div>
      </div>
    </div>,
    document.body,
  );
}
