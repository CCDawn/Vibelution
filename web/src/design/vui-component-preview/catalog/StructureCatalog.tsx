import { AlertTriangle } from "lucide-react";

import {
  VActionGroup,
  VButton,
  VEmptyState,
  VEntityList,
  VErrorSummary,
  VPanelHeader,
  VSection,
  VStateSurface,
  VStatusStrip,
  VTabs,
  VToolbar,
} from "../../../components/vui";
import { ConversationFollowupQueueBar } from "../../../components/conversation/ConversationFollowupQueueBar";
import { ConversationTranscriptLoadingState } from "../../../components/conversation/ConversationTranscriptLoadingState";
import {
  ComposerContextRing,
  ComposerContextRingPanel,
} from "../../../components/conversation/ComposerContextRing";
import type { ComposerContextRingModel } from "../../../routes/chat/composerContextModel";
import { VuiPreviewCard } from "../VuiPreviewCard";
import { VuiPreviewSection } from "../VuiPreviewSection";

const composerContextRingPreviewModel: ComposerContextRingModel = {
  usagePercent: 42,
  usageLabel: "42%",
  remainingLabel: "116K",
  capacityKnown: true,
  hitPercent: 63,
  usedLabel: "88.2K",
  empty: false,
  cacheState: "observed",
  segments: [
    { key: "prompt", name: "提示与规范", tokens: 21000, tokensLabel: "21K", pctLabel: "24%" },
    { key: "history", name: "对话历史", tokens: 12000, tokensLabel: "12K", pctLabel: "14%" },
  ],
  groups: [
    {
      key: "instructions",
      name: "提示与规范",
      tokensLabel: "21K",
      segments: [
        {
          key: "prompt",
          name: "提示与规范",
          tokens: 21000,
          tokensLabel: "21K",
          pctLabel: "24%",
          contentPreview: "系统提示与项目规范摘要",
        },
      ],
    },
    {
      key: "history",
      name: "对话历史",
      tokensLabel: "12K",
      segments: [
        {
          key: "history",
          name: "对话历史",
          tokens: 12000,
          tokensLabel: "12K",
          pctLabel: "14%",
          contentPreview: "最近会话消息摘要",
        },
      ],
    },
  ],
  detailAvailable: true,
};

export function StructureCatalog() {
  return (
    <VuiPreviewSection title="Structure">
      <VuiPreviewCard name="VPanelHeader" className="min-h-0">
        <VPanelHeader title="项目设置" />
      </VuiPreviewCard>
      <VuiPreviewCard name="VToolbar / VActionGroup" className="min-h-0">
        <VToolbar ariaLabel="操作"><VActionGroup ariaLabel="主要操作"><VButton variant="primary">保存</VButton><VButton>取消</VButton></VActionGroup></VToolbar>
      </VuiPreviewCard>
      <VuiPreviewCard name="VTabs" className="min-h-0">
        <VTabs aria-label="视图" items={[{ id: "summary", label: "总览" }, { id: "evidence", label: "证据" }]} value="summary" />
      </VuiPreviewCard>
      <VuiPreviewCard name="VStatusStrip" className="min-h-0">
        <VStatusStrip items={[{ label: "运行中", value: "1", tone: "info" }, { label: "待复核", value: "2", tone: "warning" }]} />
      </VuiPreviewCard>
      <VuiPreviewCard name="VEmptyState" className="min-h-0">
        <VEmptyState title="暂无资料" />
      </VuiPreviewCard>
      <VuiPreviewCard name="VErrorSummary" className="min-h-0">
        <VErrorSummary icon={<AlertTriangle size={14} />} summary="无法保存" />
      </VuiPreviewCard>
      <VuiPreviewCard name="VStateSurface" className="min-h-0">
        <VStateSurface tone="loading" title="加载中" />
      </VuiPreviewCard>
      <VuiPreviewCard name="ConversationFollowupQueueBar" className="col-span-full min-h-0">
        <div className="w-full rounded-[12px] border border-vui-border-subtle bg-vui-surface-panel p-3">
          <ConversationFollowupQueueBar
            items={[
              { id: "queue-1", text: "继续整理 source collection 证据" },
              { id: "queue-2", text: "补充实验对照组说明" },
            ]}
            lang="zh"
            editLabel="编辑"
            withdrawLabel="撤回"
            onUpdate={() => undefined}
            onRemove={() => undefined}
            onMove={() => undefined}
          />
        </div>
      </VuiPreviewCard>
      <VuiPreviewCard name="ConversationTranscriptLoadingState" className="col-span-full min-h-0">
        <div className="h-[360px] w-full overflow-hidden rounded-[12px] border border-vui-border-subtle bg-vui-surface-panel">
          <ConversationTranscriptLoadingState label="正在加载会话消息" />
        </div>
      </VuiPreviewCard>
      <VuiPreviewCard name="ComposerContextRing" className="col-span-full min-h-0">
        <div className="grid w-full justify-items-start gap-3 rounded-[12px] border border-vui-border-subtle bg-vui-surface-panel p-3">
          <ComposerContextRing model={composerContextRingPreviewModel} lang="zh" sessionId="preview-session" />
          <div className="w-full max-w-[324px] rounded-[12px] border border-vui-border-subtle bg-vui-surface-row p-3">
            <ComposerContextRingPanel model={composerContextRingPreviewModel} lang="zh" />
          </div>
        </div>
      </VuiPreviewCard>
      <VuiPreviewCard name="VEntityList" className="min-h-0">
        <VEntityList ariaLabel="成员" items={[{ id: "evidence", label: "证据 Agent", meta: "运行中" }]} renderItem={(item) => <span>{item.label}</span>} />
      </VuiPreviewCard>
      <VuiPreviewCard name="VSection" className="min-h-0">
        <VSection title="知识包" />
      </VuiPreviewCard>
    </VuiPreviewSection>
  );
}
