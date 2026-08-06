import { useState } from "react";

import {
  AgentBulkActionBar,
  AgentDenseList,
  AgentFilterRail,
  AgentPageHeader,
  AgentPermissionPresetControl,
  AgentSummaryStrip,
  AgentWorkspacePanel,
} from "../../../components/vui/product/agent-management";
import { VButton } from "../../../components/vui";
import { VuiPreviewCard } from "../VuiPreviewCard";
import { VuiPreviewSection } from "../VuiPreviewSection";

const columns = [{
  id: "research",
  label: "科研执行",
  count: 3,
  rows: [
    {
      id: "search", name: "检索 Agent", roleLabel: "资料检索", roleTone: "research", avatarInitials: "检",
      modelLabel: "mimo-v2.5", promptLabel: "检索资料", runtimeLabel: "运行中", runtimeTone: "running",
      modes: ["搜索"], issueLabel: "", issueTone: "ok", active: false, bulkSelected: false, selectLabel: "选择检索 Agent",
    },
    {
      id: "evidence", name: "证据 Agent", roleLabel: "证据边界", roleTone: "research", avatarInitials: "证",
      modelLabel: "mimo-v2.5", promptLabel: "核验证据", runtimeLabel: "冲突 3", runtimeTone: "blocked",
      modes: ["核验"], issueLabel: "冲突 3", issueTone: "warning", issueSummary: "需要处理三项冲突。", active: false, bulkSelected: false, selectLabel: "选择证据 Agent",
    },
  ],
}];

export function AgentCatalog() {
  const [search, setSearch] = useState("");
  const [preset, setPreset] = useState<"request_approval" | "auto_review" | "full_access">("request_approval");

  return (
    <VuiPreviewSection title="Agent">
      <VuiPreviewCard name="AgentPageHeader" className="col-span-full min-h-0">
        <div className="w-full"><AgentPageHeader eyebrow="Agent" title="研究 Agent" /></div>
      </VuiPreviewCard>
      <VuiPreviewCard name="AgentSummaryStrip" className="min-h-0">
        <AgentSummaryStrip ariaLabel="摘要" metrics={[{ id: "running", label: "运行中", value: 1, tone: "info" }, { id: "review", label: "待复核", value: 1, tone: "warning" }]} />
      </VuiPreviewCard>
      <VuiPreviewCard name="AgentPermissionPresetControl" className="min-h-0">
        <AgentPermissionPresetControl value={preset} lang="zh" surface="settings" disabled={false} pending={false} onChange={setPreset} />
      </VuiPreviewCard>
      <VuiPreviewCard name="AgentWorkspacePanel" className="min-h-0">
        <AgentWorkspacePanel ariaLabel="证据 Agent" className="w-full !min-h-20 !content-center">证据 Agent</AgentWorkspacePanel>
      </VuiPreviewCard>
      <VuiPreviewCard name="AgentBulkActionBar" className="min-h-0">
        <div className="w-full"><AgentBulkActionBar ariaLabel="批量操作" summary={<strong>已选择 2 项</strong>} mutationActions={<VButton variant="primary">保存</VButton>} /></div>
      </VuiPreviewCard>
      <VuiPreviewCard name="AgentFilterRail" className="min-h-0">
        <AgentFilterRail ariaLabel="筛选" searchValue={search} searchPlaceholder="搜索" onSearchChange={setSearch} activeGroupId="running" onSelectGroup={() => undefined} moreFiltersLabel="更多筛选" sections={[{ id: "status", label: "状态", groups: [{ id: "running", label: "运行中", count: 1 }, { id: "review", label: "待复核", count: 1 }] }]} />
      </VuiPreviewCard>
      <VuiPreviewCard name="AgentDenseList" className="min-h-0">
        <div className="w-full"><AgentDenseList columns={columns} columnLabels={{ agent: "Agent", model: "模型", prompt: "提示词", runtime: "运行", modes: "模式", reminders: "提醒" }} onSelectRow={() => undefined} onToggleBulk={() => undefined} /></div>
      </VuiPreviewCard>
    </VuiPreviewSection>
  );
}
