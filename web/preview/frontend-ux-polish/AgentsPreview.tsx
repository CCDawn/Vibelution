import { useState } from "react";
import { useLocation } from "react-router-dom";
import { VDialog, VStateSurface } from "../../src/components/vui";
import { AgentWorkspaceLayoutPanel } from "../../src/routes/AgentWorkspaceLayoutPanel";
import { AgentManagementHeaderPanel } from "../../src/routes/AgentManagementHeaderPanel";
import styles from "../../src/routes/AgentsRoute.styles";

const noop = () => undefined;
const bulkCopy = {
  bulkSelected: "已选择", bulkClear: "取消选择", bulkSelectVisible: "选择本页", bulkPromptLabel: "提示词",
  bulkPromptPlaceholder: "选择提示词", bulkApplyPrompt: "应用", bulkArchive: "归档", bulkPurge: "清除",
  bulkWorking: "处理中", bulkArchiveConfirm: "确认归档", bulkPurgeConfirm: "确认清除", cancelCreate: "取消",
};

export function AgentsPreview() {
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState("alpha");
  const [createOpen, setCreateOpen] = useState(false);
  const [refreshed, setRefreshed] = useState(false);
  const location = useLocation();
  const rows = [{ id: "alpha", name: "研究 Agent" }, { id: "beta", name: "对话 Agent" }]
    .filter((item) => item.name.includes(search))
    .map((item) => ({ ...item, roleLabel: "通用 Agent", roleTone: "neutral", avatarInitials: item.id.slice(0,1).toUpperCase(),
      modelLabel: "默认模型", promptLabel: "默认提示词", runtimeLabel: "空闲", runtimeTone: "idle", modes: [],
      issueLabel: "正常", issueTone: "ok", active: selected === item.id, bulkSelected: false, selectLabel: `选择 ${item.name}` }));
  return <>
    <AgentWorkspaceLayoutPanel className={styles.route} ariaLabel="Agent 管理验收" title="不应重复显示的标题"
      toolbar={<AgentManagementHeaderPanel copy={{ createAgent: "新增 Agent", refresh: "刷新 Agent" }} onCreateAgent={() => setCreateOpen(true)} onRefresh={() => setRefreshed(true)} />}
      filterRail={{ ariaLabel: "Agent 筛选", searchValue: search, searchPlaceholder: "搜索 Agent", onSearchChange: setSearch,
        sections: [{ id: "modes", label: "分组", groups: [{ id: "all", label: "全部 Agent", count: 2 }] }], activeGroupId: "all", onSelectGroup: noop }}
      listWorkspace={{ ariaLabel: "Agent 列表", headerTitle: "全部 Agent", visibleAgentCount: rows.length,
        bulkOperations: { copy: bulkCopy, selectedCount: 0, visibleCount: rows.length, allVisibleSelected: false, pending: false, selectedPromptTemplateId: "", promptTemplateOptions: [], onSelectVisible: noop, onClearSelection: noop, onPromptTemplateChange: noop, onApplyPromptTemplate: noop, onArchive: noop, onPurge: noop },
        listState: { copy: { loadFailed: "加载失败", loading: "加载中", noAgents: "没有匹配的 Agent", retry: "重试", refreshing: "刷新中", staleError: "更新失败", model: "模型", prompt: "提示词", runtimeStatus: "状态", modeMembership: "模式", statusReminders: "提醒" },
          columns: [{ id: "all", label: "Agent", count: rows.length, rows }], visibleAgentCount: rows.length, isError: false, error: null, isPending: false, isFetching: false, hasWorkspace: true, onRetry: noop, onSelectRow: setSelected, onToggleBulk: noop } }}
      detailWorkspace={{ ariaLabel: "Agent 详情", returnBanner: null, bulkConfig: null, emptySelectionTitle: "请选择 Agent",
        selectedContent: <VStateSurface tone="info" title={selected === "alpha" ? "研究 Agent" : "对话 Agent"}>
          <p role="status">{refreshed ? "刷新按钮已响应 · 模拟数据" : "选择列表项查看详情"}</p><p>导航路径：{location.pathname}</p>
        </VStateSurface> }} />
    <VDialog open={createOpen} onOpenChange={setCreateOpen} title="新增 Agent · 按钮可正常点击">
      <p>隔离验收：未创建任何真实 Agent。</p>
    </VDialog>
  </>;
}
