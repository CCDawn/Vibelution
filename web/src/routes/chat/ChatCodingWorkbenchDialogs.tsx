/**
 * Chat workbench dialogs that render inside the session shell:
 * group management, cache detail, agent create, and danger confirm.
 * The rerun file-choice dialog stays beside the shell.
 */
import { lazy, Suspense, type Dispatch, type RefObject, type SetStateAction } from "react";
import type { NavigateFunction } from "react-router-dom";

import type {
  AgentInstance,
  SessionAgentPromptSnapshot,
  SessionLlmPayloadTrace,
  SessionPromptAssemblyManifest,
} from "../../api/types";
import type { TranslationKey } from "../../i18n/dictionary";
import { cacheCompositionSegmentLabel } from "./chatRoutePresentation";
import {
  ChatGroupManagementDialog,
  type ChatGroupManagementDialogProps,
} from "./ChatGroupManagementDialog";
import { ChatDangerConfirmDialog } from "./ChatDangerConfirmDialog";
import type { ChatCacheDetailViewModel } from "./chatCacheDetailModel";
import {
  type ChatWorkbenchConfirmPresentation,
} from "./useChatWorkbenchConfirmDialog";
import type { RightIndexPanel } from "./useChatConversationIndexChrome";

const AgentCreateWizardDialog = lazy(() =>
  import("../agent-create/AgentCreateWizardDialog").then((module) => ({
    default: module.AgentCreateWizardDialog,
  })),
);

const CacheDetailDialog = lazy(() =>
  import("./CacheDetailDialog").then((module) => ({
    default: module.CacheDetailDialog,
  })),
);

export type ChatCodingWorkbenchDialogsProps = ChatGroupManagementDialogProps & {
  cacheDetailOpen: boolean;
  cacheDetailAvailable: boolean;
  cacheDetailViewModel: ChatCacheDetailViewModel;
  t: (key: TranslationKey) => string;
  numberFormatter: Intl.NumberFormat;
  closeCacheDetail: () => void;
  promptSnapshot?: SessionAgentPromptSnapshot;
  promptAssembly?: SessionPromptAssemblyManifest;
  lastLlmPayloadTrace?: SessionLlmPayloadTrace | null;
  agentCreateWizardOpen: boolean;
  agentCreateTriggerRef: RefObject<HTMLButtonElement | null>;
  setAgentCreateWizardOpen: Dispatch<SetStateAction<boolean>>;
  setSelectedAgentId: (agentId: string) => void;
  setRightIndexPanel: Dispatch<SetStateAction<RightIndexPanel>>;
  handleOpenAgent: (agent: AgentInstance) => boolean;
  navigate: NavigateFunction;
  pendingConfirm: unknown;
  pendingConfirmPresentation: ChatWorkbenchConfirmPresentation | null;
  dismissPendingConfirm: () => void;
  confirmPendingWorkbenchAction: () => void;
};

export function ChatCodingWorkbenchDialogs({
  cacheDetailOpen,
  cacheDetailAvailable,
  cacheDetailViewModel,
  t,
  numberFormatter,
  closeCacheDetail,
  promptSnapshot,
  promptAssembly,
  lastLlmPayloadTrace,
  agentCreateWizardOpen,
  agentCreateTriggerRef,
  setAgentCreateWizardOpen,
  setSelectedAgentId,
  setRightIndexPanel,
  handleOpenAgent,
  navigate,
  pendingConfirm,
  pendingConfirmPresentation,
  dismissPendingConfirm,
  confirmPendingWorkbenchAction,
  ...groupDialog
}: ChatCodingWorkbenchDialogsProps) {
  return (
    <>
      <ChatGroupManagementDialog {...groupDialog} />
      {cacheDetailOpen && cacheDetailAvailable ? (
        <Suspense fallback={null}>
          <CacheDetailDialog
            {...cacheDetailViewModel}
            closeLabel={groupDialog.lang === "zh" ? "关闭缓存详情" : "Close cache details"}
            lang={groupDialog.lang}
            missingSegmentLabel={cacheCompositionSegmentLabel("missing", "missing", t)}
            numberFormatter={numberFormatter}
            onClose={closeCacheDetail}
            previousCacheHitLabel={t("previousCacheHit")}
            promptSnapshot={promptSnapshot}
            promptAssembly={promptAssembly}
            lastLlmPayloadTrace={lastLlmPayloadTrace}
          />
        </Suspense>
      ) : null}
      {agentCreateWizardOpen ? (
        <Suspense fallback={null}>
          <AgentCreateWizardDialog
            open={agentCreateWizardOpen}
            triggerRef={agentCreateTriggerRef}
            triggerId="chat-agent-create-trigger"
            onClose={() => setAgentCreateWizardOpen(false)}
            onCreated={(agent) => {
              setSelectedAgentId(agent.agentId);
              setRightIndexPanel("conversations");
            }}
            onStartConversation={async (agent) => {
              if (!agent.directSessionId) return false;
              handleOpenAgent(agent);
              return true;
            }}
            onOpenAdvancedConfig={(agent) => {
              setAgentCreateWizardOpen(false);
              navigate(`/agents?agent=${encodeURIComponent(agent.agentId)}&pane=config&returnTo=${encodeURIComponent("/chat")}`);
            }}
          />
        </Suspense>
      ) : null}
      <ChatDangerConfirmDialog
        open={Boolean(pendingConfirm)}
        title={pendingConfirmPresentation?.title ?? ""}
        confirmLabel={pendingConfirmPresentation?.confirmLabel ?? ""}
        cancelLabel={groupDialog.lang === "zh" ? "取消" : "Cancel"}
        confirmPending={pendingConfirmPresentation?.confirmPending ?? false}
        onOpenChange={(open) => {
          if (!open) {
            dismissPendingConfirm();
          }
        }}
        onCancel={dismissPendingConfirm}
        onConfirm={confirmPendingWorkbenchAction}
      />
    </>
  );
}
