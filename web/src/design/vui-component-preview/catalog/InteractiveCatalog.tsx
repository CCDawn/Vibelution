import { MoreHorizontal, Power } from "lucide-react";
import { useState } from "react";

import {
  VButton,
  VCommandPalette,
  VConfirmDialog,
  VContextualHint,
  VDialog,
  VDropdownMenu,
  VHoverCard,
  VNativeButton,
  VPopover,
  VRouteLinkButton,
  VTooltip,
  VWorkbenchPowerMenu,
} from "../../../components/vui";
import { ConversationTurnModelControl } from "../../../components/conversation/ConversationTurnModelControl";
import type { SessionLlmModelOption, SessionModelSelection } from "../../../api/types";
import { VuiPreviewCard } from "../VuiPreviewCard";
import { VuiPreviewSection } from "../VuiPreviewSection";

const turnModelChoices: SessionLlmModelOption[] = [
  {
    modelId: "qwen3-max", modelRef: "qwen3-max", model: "qwen3-max", label: "Qwen3 Max",
    providerId: "dashscope", providerLabel: "DashScope", providerKind: "openai", apiKeyConfigured: true, missingApiKey: false,
    supportsReasoningEffort: true, reasoningEffortValues: ["low", "medium", "high"],
    reasoningEffortOptions: [], defaultReasoningEffort: "medium", isDefault: true,
  },
  {
    modelId: "deepseek-v3.2", modelRef: "deepseek-v3.2", model: "deepseek-v3.2", label: "DeepSeek V3.2",
    providerId: "deepseek", providerLabel: "DeepSeek", providerKind: "openai", apiKeyConfigured: true, missingApiKey: false,
    supportsReasoningEffort: false, reasoningEffortValues: [], reasoningEffortOptions: [],
    defaultReasoningEffort: "", isDefault: false,
  },
  {
    modelId: "glm-5.3", modelRef: "glm-5.3", model: "glm-5.3", label: "GLM-5.3",
    providerId: "bigmodel", providerLabel: "BigModel", providerKind: "anthropic", apiKeyConfigured: true, missingApiKey: false,
    supportsReasoningEffort: true, reasoningEffortValues: ["low", "medium", "high"],
    reasoningEffortOptions: [], defaultReasoningEffort: "high", isDefault: false,
  },
];

export function InteractiveCatalog() {
  const [dialogOpen, setDialogOpen] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [turnModelSelection, setTurnModelSelection] = useState<SessionModelSelection | null>(null);

  return (
    <VuiPreviewSection title="Interactive">
      <VuiPreviewCard name="ConversationTurnModelControl">
        <ConversationTurnModelControl
          choices={turnModelChoices}
          sessionDefaultModelId="qwen3-max"
          selection={turnModelSelection}
          disabled={false}
          onSelectionChange={setTurnModelSelection}
        />
      </VuiPreviewCard>
      <VuiPreviewCard name="VRouteLinkButton">
        <VRouteLinkButton to="/agents">打开</VRouteLinkButton>
      </VuiPreviewCard>
      <VuiPreviewCard name="VNativeButton">
        <VNativeButton className="border border-vui-border-subtle bg-vui-control-muted px-3 py-1.5 text-vui-xs font-semibold text-vui-fg-primary">确认</VNativeButton>
      </VuiPreviewCard>
      <VuiPreviewCard name="VTooltip">
        <VTooltip content="知识包">
          <VButton variant="secondary">悬停</VButton>
        </VTooltip>
      </VuiPreviewCard>
      <VuiPreviewCard name="VHoverCard">
        <VHoverCard
          content={
            <>
              <p>知识包摘要：近 7 天新增 12 条证据。</p>
              <p className="mt-2 text-vui-fg-secondary">停留查看关键状态，移开即收起。</p>
            </>
          }
        >
          <VButton variant="secondary">悬停预览</VButton>
        </VHoverCard>
      </VuiPreviewCard>
      <VuiPreviewCard name="VContextualHint">
        <VContextualHint label="详情" content="知识包" />
      </VuiPreviewCard>
      <VuiPreviewCard name="VDropdownMenu">
        <VDropdownMenu
          aria-label="更多操作"
          trigger={<VButton isIconOnly aria-label="更多操作" icon={<MoreHorizontal size={16} />} />}
          items={[{ id: "rename", label: "重命名", onSelect: () => undefined }, { id: "remove", label: "移除", danger: true, onSelect: () => undefined }]}
        />
      </VuiPreviewCard>
      <VuiPreviewCard name="VPopover">
        <VPopover aria-label="筛选" trigger={<VButton variant="secondary">筛选</VButton>}>
          <VNativeButton className="px-2 py-1 text-vui-xs text-vui-fg-primary">已验证</VNativeButton>
        </VPopover>
      </VuiPreviewCard>
      <VuiPreviewCard name="VDialog">
        <VButton variant="secondary" onPress={() => setDialogOpen(true)}>打开</VButton>
        <VDialog open={dialogOpen} onOpenChange={setDialogOpen} title="实验协议" />
      </VuiPreviewCard>
      <VuiPreviewCard name="VConfirmDialog">
        <VButton variant="danger" onPress={() => setConfirmOpen(true)}>移除</VButton>
        <VConfirmDialog
          open={confirmOpen}
          onOpenChange={setConfirmOpen}
          title="移除项目"
          cancelLabel="取消"
          confirmLabel="移除"
          tone="danger"
          onConfirm={() => setConfirmOpen(false)}
        />
      </VuiPreviewCard>
      <VuiPreviewCard name="VWorkbenchPowerMenu">
        <VWorkbenchPowerMenu
          labels={{ menu: "运行", restart: "重启", stop: "停止", forceStop: "强制停止" }}
          variant="labeled"
          triggerIcon={<Power size={15} />}
          onAction={() => undefined}
        />
      </VuiPreviewCard>
      <VuiPreviewCard name="VCommandPalette">
        <VButton variant="secondary" onPress={() => setPaletteOpen(true)}>打开命令面板</VButton>
        <VCommandPalette
          open={paletteOpen}
          onOpenChange={setPaletteOpen}
          items={[
            { id: "cmd:current", group: "命令", label: "前往当前任务", onRun: () => undefined },
            {
              id: "question:SCI-001",
              group: "题目",
              label: "SCI-001",
              detail: "What makes prime numbers so special?",
              onRun: () => undefined,
            },
          ]}
          labels={{
            searchPlaceholder: "搜索题目或命令…",
            emptyTitle: "没有匹配项",
            hint: "↑↓ 选择 · Enter 执行 · Esc 关闭",
          }}
        />
      </VuiPreviewCard>
    </VuiPreviewSection>
  );
}
