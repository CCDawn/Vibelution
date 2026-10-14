import { useCallback, useEffect, useState, type CSSProperties, type ReactNode } from "react";
import { ArrowRight, Beaker, Check, ChevronRight, FileText, GitBranch, Home, MessageSquare, Play, RefreshCw, Search, Settings2, Users } from "lucide-react";
import { VButton, VDialog, VNativeSelect, VPanel, VPanelHeader, VSessionWorkbenchPage, VStateSurface, VStatusChip, VTextarea, VuiProvider, VWorkbenchPage } from "../../src/components/vui";
import { WORKBENCH_LAYOUT_IDS } from "../../src/components/layout/workbenchLayoutIds";
import { usePersistedPaneResize } from "../../src/components/layout/usePersistedPaneResize";
import { PaneResizeHandle } from "../../src/components/layout/PaneResizeHandle";
import chatStyles from "../../src/routes/ChatCodingRoute.styles";
import { vuiRailFillClass } from "../../src/design/vuiSurfaceRecipes";
import { TeamConversationPreview } from "./TeamConversationPreview";
import { OrganizationCanvasPreview, WorkflowCanvasPreview, workflowGraph } from "./TeamCanvasPreview";

type View = "home" | "sources" | "experiment" | "organization" | "workflow";
type Scene = "normal" | "loading" | "empty" | "error";
const pages: { id: View; label: string; icon: typeof Home }[] = [
  { id: "home", label: "团队主页", icon: Home },
  { id: "sources", label: "资料收集", icon: Search },
  { id: "experiment", label: "实验工作台", icon: Beaker },
  { id: "organization", label: "组织画布", icon: GitBranch },
  { id: "workflow", label: "流程画布", icon: GitBranch },
];
const defaultMembers = [
  { name: "林舟", role: "任务协调", initials: "林", note: "拆解任务，协调成员并汇总结论" },
  { name: "苏青", role: "资料研究", initials: "苏", note: "检索来源，核对证据与适用范围" },
  { name: "顾言", role: "实现与验证", initials: "顾", note: "执行方案，记录测试和验收结果" },
];
const teams = [
  { id: "development", name: "开发团队", topic: "梳理团队工作台布局，完成统一页面外框预览", members: defaultMembers },
  { id: "research", name: "研究团队", topic: "核对统一布局的研究资料与证据", members: [
    { name: "陈默", role: "研究协调", initials: "陈", note: "明确研究问题并汇总证据" },
    { name: "许宁", role: "来源核验", initials: "许", note: "检查资料来源与适用范围" },
    { name: "周遥", role: "实验设计", initials: "周", note: "设计验证步骤并记录结果" },
  ] },
  { id: "validation", name: "验证团队", topic: "检查四个团队页面的布局与按钮反馈", members: [
    { name: "沈予", role: "验收协调", initials: "沈", note: "组织界面验收并跟进问题" },
    { name: "陆川", role: "交互验证", initials: "陆", note: "检查按钮反馈与页面状态" },
    { name: "程晓", role: "结果记录", initials: "程", note: "整理测试证据与验收结论" },
  ] },
];
const sectionTitle = "text-[13px] font-medium text-[var(--fg-primary)]";
const quiet = "text-[12px] leading-5 text-[var(--fg-tertiary)]";

function Member({ member, subtitle }: { member: typeof defaultMembers[number]; subtitle?: string }) {
  return <div className="flex min-w-0 items-center gap-2.5">
    <span className="grid h-7 w-7 shrink-0 place-items-center rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-base)] text-[12px] text-[var(--fg-secondary)]">{member.initials}</span>
    <div className="min-w-0"><p className="text-[13px] font-medium">{member.name}</p><p className={quiet}>{subtitle || member.role}</p></div>
  </div>;
}

function TeamPanel({ title, children, id, actions, titleControl, fill = false, rail = false }: { title: string; children: ReactNode; id: string; actions?: ReactNode; titleControl?: ReactNode; fill?: boolean; rail?: boolean }) {
  return <VPanel ariaLabel={title} className={"flex h-full min-h-0 flex-col overflow-hidden " + (rail ? `${vuiRailFillClass} !rounded-none !border-0` : "")} data-testid={id}>
    <VPanelHeader title={titleControl ?? title} headingLevel={titleControl ? null : 2} actions={actions} data-vui="team-preview-panel-header" className="h-11 shrink-0 items-center! border-b border-[var(--vui-border-subtle)] px-2 py-0 [&>div:first-child]:shrink-0 [&>div:last-child]:overflow-x-auto [&>div:last-child]:justify-start [&_h2]:text-[14px] [&_h2]:font-medium [&_h2]:leading-6" />
    <div className={"flex min-h-0 min-w-0 flex-1 flex-col " + (fill ? "overflow-hidden p-0" : "overflow-auto p-2")} data-vui="team-preview-panel-body">{children}</div>
  </VPanel>;
}

/** Shared chat rail backdrop with one rounded white content pane for every view. */
const framePanes = [{ id: "rail", defaultWidth: 220, minWidth: 200, maxWidth: 280 }, { id: "inspector", defaultWidth: 312, minWidth: 280, maxWidth: 380 }];
function TeamFrame({ title, toolbar, navigation, body, inspector, inspectorTitle, teamName, teamSwitcher, fillBody }: {
  title: string; toolbar: ReactNode; navigation: ReactNode; body: ReactNode; inspector: ReactNode; inspectorTitle: string; teamName: string; teamSwitcher: ReactNode; fillBody: boolean;
}) {
  const resize = usePersistedPaneResize({ layoutId: WORKBENCH_LAYOUT_IDS.teams, panes: framePanes });
  const attach = useCallback((element: HTMLDivElement | null) => { resize.layoutRef.current = element; resize.registerSplitContainer(element); }, [resize.layoutRef, resize.registerSplitContainer]);
  return <div className="flex h-full min-h-0 flex-col bg-vui-surface-rail p-1 [--shell-surface:var(--vui-surface-rail)]">
    <VSessionWorkbenchPage ref={attach} ariaLabel="统一团队工作台" domainRecipe="teams-session-workbench" layoutId={WORKBENCH_LAYOUT_IDS.teams}
      data-testid="unified-team-frame" className={chatStyles.layout + " !h-full !max-h-full"}
      hostStyle={{ ...resize.paneVariablesStyle, "--chat-left-pane-width": "var(--pane-w-rail)", "--chat-right-pane-width": "var(--pane-w-inspector)", "--chat-pane-gutter": "6px" } as CSSProperties}
      indexRail={<aside className="flex min-h-0 min-w-0 flex-col [grid-column:1] [grid-row:1]"><TeamPanel rail title={teamName} titleControl={teamSwitcher} id="unified-navigation"><nav aria-label="团队工作台导航" className="flex min-h-0 flex-1 flex-col">{navigation}</nav></TeamPanel></aside>}
      leftResizeHandle={<PaneResizeHandle label="调整左侧栏宽度" valueNow={resize.widths.rail} valueMin={200} valueMax={280} className="[grid-column:2] [grid-row:1]" onPointerDown={(event) => resize.startResize("rail", event)} onKeyDown={(event) => resize.onResizeKeyDown("rail", event)} />}
      session={<main className="mx-1 flex min-h-0 min-w-0 flex-col [grid-column:3] [grid-row:1]"><TeamPanel title={title} actions={toolbar} fill={fillBody} id="unified-content">{body}</TeamPanel></main>}
      rightResizeHandle={<PaneResizeHandle label="调整右侧栏宽度" valueNow={resize.widths.inspector} valueMin={280} valueMax={380} className="[grid-column:4] [grid-row:1]" onPointerDown={(event) => resize.startResize("inspector", event, { direction: -1 })} onKeyDown={(event) => resize.onResizeKeyDown("inspector", event, { direction: -1 })} />}
      statusRail={<aside className="flex min-h-0 min-w-0 flex-col [grid-column:5] [grid-row:1]"><TeamPanel rail title={inspectorTitle} id="unified-inspector">{inspector}</TeamPanel></aside>} />
  </div>;
}

export function TeamLayoutPreview() {
  const params = new URLSearchParams(location.search);
  const [view, setView] = useState<View>(pages.some((page) => page.id === params.get("view")) ? params.get("view") as View : "home");
  const [scene, setScene] = useState<Scene>((["normal", "loading", "empty", "error"].includes(params.get("state") || "")) ? params.get("state") as Scene : "normal");
  const [theme, setTheme] = useState("light");
  const [dialog, setDialog] = useState<"members" | "start" | null>(null);
  const [teamId, setTeamId] = useState(params.get("view") === "workflow" ? "research" : teams[0].id);
  const team = teams.find((item) => item.id === teamId)!;
  const members = team.members;
  const [topic, setTopic] = useState(teams[0].topic);
  const [running, setRunning] = useState(false);
  const [selectedMember, setSelectedMember] = useState(0);
  const [selectedSource, setSelectedSource] = useState(0);
  const [experimentDone, setExperimentDone] = useState(false);
  const [notice, setNotice] = useState("");
  const [homeMode, setHomeMode] = useState<"canvas" | "conversation">(params.get("mode") === "conversation" ? "conversation" : "canvas");
  const [directMember, setDirectMember] = useState<typeof defaultMembers[number] | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>("execute");
  const selectedNode = workflowGraph.nodes.find((node) => node.nodeId === selectedNodeId);
  const workflowVisible = view === "workflow" || (view === "home" && homeMode === "canvas" && teamId === "research");
  const organizationVisible = view === "organization" || (view === "home" && homeMode === "canvas" && teamId !== "research");
  const current = pages.find((page) => page.id === view)!;
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    history.replaceState(null, "", `${location.pathname}?view=${view}&state=${scene}&mode=${homeMode}`);
  }, [view, scene, theme, homeMode]);
  function switchPage(next: View) { setView(next); setNotice(""); }
  function switchTeam(nextId: string) {
    const next = teams.find((item) => item.id === nextId);
    if (!next || nextId === teamId) return;
    setTeamId(next.id);
    setTopic(next.topic);
    setView("home");
    setScene("normal");
    setDialog(null);
    setRunning(false);
    setSelectedMember(0);
    setSelectedSource(0);
    setExperimentDone(false);
    setDirectMember(null);
    setSelectedNodeId("execute");
    setNotice(`已切换到${next.name}（示例数据）。`);
  }
  const teamSwitcher = <VNativeSelect aria-label="切换团队" value={teamId} onChange={(event) => switchTeam(event.target.value)} className="h-7 w-[180px] text-[14px] font-medium">
    {teams.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
  </VNativeSelect>;

  const navigation = <>
    <div className="flex items-center justify-between gap-2 pb-4"><p className={quiet}>3 位成员 · 本地协作</p><VStatusChip tone="success">正常</VStatusChip></div>
    <div className="grid gap-1 pb-4">{pages.filter((page) => page.id !== "workflow" || teamId === "research").map((page) => <VButton key={page.id} variant="ghost" density="compact" icon={<page.icon size={15} />} aria-current={view === page.id ? "page" : undefined}
      className={`w-full justify-start aria-[current=page]:bg-[var(--vui-selection-bg)] aria-[current=page]:text-[var(--fg-primary)] ${view === page.id ? "font-medium" : "text-[var(--fg-secondary)]"}`} onClick={() => switchPage(page.id)}>{page.label}</VButton>)}</div>
    <div className="border-t border-[var(--vui-border-subtle)] pt-4"><p className="mb-3 text-[12px] font-medium text-[var(--fg-tertiary)]">团队成员</p><div className="grid gap-4">{members.map((member) => <div key={member.name}><Member member={member} /></div>)}</div></div>
    <div className="mt-auto pt-4"><VButton variant="ghost" density="compact" icon={<Settings2 size={15} />} className="w-full justify-start text-[var(--fg-secondary)]" onClick={() => setDialog("members")}>团队设置</VButton></div>
  </>;

  const home = <div data-preview="native-conversation-flow" className="flex h-full min-h-0 min-w-0 flex-col [&_.groupConversationFrame]:grid-rows-[minmax(0,1fr)_auto] [&_.groupConversationHeader]:hidden">
    <TeamConversationPreview key={teamId} teamId={teamId} teamName={team.name} members={members} topic={topic} running={running} directMember={directMember}
      onStart={(nextTopic) => { setTopic(nextTopic); setRunning(true); setNotice("本轮运行仅为本地演示，未调用模型。"); }} onStop={() => { setRunning(false); setNotice("示例轮次已停止，发言保留。"); }} onNotice={setNotice} />
  </div>;

  const sources = [
    { title: "团队主页与阶段页的布局差异", type: "项目源码", description: "核对主页、资料收集、实验和组织结构的页面外框与滚动区域。", status: "已核验" },
    { title: "VUI 公共页面布局与栏位规则", type: "组件文档", description: "复用公共页面壳、分栏和尺寸记忆，集中维护标题与边界。", status: "已纳入" },
    { title: "团队管理按钮的真实操作记录", type: "验收证据", description: "添加成员、职责保存与读回，以及归档影响提示的完整验证。", status: "已核验" },
    { title: "统一页面外框的桌面预览", type: "设计预览", description: "对比不同业务内容下的共同布局，确认后再正式接入。", status: "待确认" },
  ];
  const sourceView = <div><div className="border-b border-[var(--vui-border-subtle)] pb-4"><div className="flex items-center justify-between"><p className={quiet}>当前阶段</p><span className={quiet}>4 条资料</span></div><h2 className="mt-2 text-[20px] font-medium leading-8">围绕团队布局整理研究资料</h2><p className="mt-2 text-[13px] leading-6 text-[var(--fg-secondary)]">围绕同一问题整理来源，保留核验状态。</p></div><div className="divide-y divide-[var(--vui-border-subtle)]">{sources.map((source, index) => <article key={source.title} className="py-5"><div className="flex items-center justify-between gap-4"><VButton variant="ghost" density="compact" className="min-w-0 justify-start text-left" icon={<FileText size={16} />} onClick={() => setSelectedSource(index)}>{source.title}</VButton><VStatusChip tone={source.status === "待确认" ? "warning" : "success"}>{source.status}</VStatusChip></div><p className="ml-7 mt-2 text-[13px] leading-6 text-[var(--fg-secondary)]">{source.description}</p><p className={`${quiet} ml-7 mt-2`}>{source.type} · 今天更新</p></article>)}</div></div>;

  const experiment = <div><div className="border-b border-[var(--vui-border-subtle)] pb-4"><p className={quiet}>当前实验</p><h2 className="mt-2 text-[20px] font-medium leading-8">统一布局的页面切换验证</h2><p className="mt-2 text-[13px] leading-6 text-[var(--fg-secondary)]">目标：业务内容变化时，页面骨架保持稳定。</p></div><div className="mt-5 space-y-6"><section><h3 className={sectionTitle}>验证假设</h3><p className="mt-2 text-[14px] leading-7 text-[var(--fg-secondary)]">主页、资料收集、实验和组织结构共用同一套标题、导航、正文和详情区后，可以消除由页面外框差异造成的视觉跳动。</p></section><section><h3 className={sectionTitle}>本轮检查</h3><div className="mt-3 divide-y divide-[var(--vui-border-subtle)]">{["四个页面的标题栏高度与分栏边界相同", "正文只在自己的区域内滚动", "加载、空白和错误状态保留页面骨架", "成员与任务操作继续使用现有控件"].map((text, index) => <div key={text} className="flex items-center gap-3 py-3"><span className="grid h-5 w-5 place-items-center rounded border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-base)] text-[11px]">{experimentDone ? <Check size={12} /> : index + 1}</span><p className="text-[13px] text-[var(--fg-secondary)]">{text}</p></div>)}</div></section>{experimentDone && <VStateSurface tone="info" title="示例验证已完成">页面骨架保持一致。这里展示模拟结果，正式验收仍需接入实际页面。</VStateSurface>}</div></div>;

  const organization = <OrganizationCanvasPreview key={teamId} teamId={teamId} members={members} selectedMember={selectedMember} onSelectMember={setSelectedMember} onNotice={setNotice} />;
  const workflow = <WorkflowCanvasPreview selectedNodeId={selectedNodeId} onSelectNode={setSelectedNodeId} />;
  const homeBody = homeMode === "conversation" ? home : teamId === "research" ? workflow : organization;
  const stateView = <div className="grid h-full min-h-[400px] place-items-center"><VStateSurface className="w-full max-w-[460px]" tone={scene === "loading" ? "loading" : scene === "error" ? "error" : "empty"} title={scene === "loading" ? "正在读取团队内容" : scene === "error" ? "团队内容暂时无法读取" : "这里还没有任务内容"}
    skeletonLines={scene === "loading" ? 4 : undefined} actions={scene !== "loading" ? <VButton variant="secondary" onClick={() => setScene("normal")}>{scene === "error" ? "重新读取" : "查看示例任务"}</VButton> : undefined}>
    {scene === "error" ? "保留当前团队与导航。重新读取成功后，内容会在原位置恢复。" : scene === "empty" ? "选择已有任务或开始新一轮，页面外框与操作区继续保留。" : "标题、导航和详情栏继续保持原位。"}
  </VStateSurface></div>;

  const inspector = <div className="space-y-6">
    <section><p className={quiet}>{scene !== "normal" ? "内容恢复后继续操作，当前布局保持不变。" : workflowVisible ? "选择节点查看任务、负责人和运行状态" : organizationVisible ? "选择成员查看角色与职责" : view === "home" ? "围绕当前任务继续协作" : view === "sources" ? sources[selectedSource].type : view === "experiment" ? "检查步骤与结果记录" : "团队成员的角色与职责"}</p></section>
    {workflowVisible ? <section><h3 className={sectionTitle}>{selectedNode?.label || "选择流程节点"}</h3><p className="mt-3 text-[13px] leading-6 text-[var(--fg-secondary)]">{selectedNode?.description || "点击画布节点查看任务与状态。"}</p>{selectedNode && <><div className="mt-4"><VStatusChip tone={selectedNode.status === "running" ? "accent" : selectedNode.status === "succeeded" ? "success" : "neutral"}>{selectedNode.status === "running" ? "示例运行中" : selectedNode.status === "succeeded" ? "示例已完成" : "示例待执行"}</VStatusChip></div><p className={`${quiet} mt-4`}>负责人：{selectedNode.actorKind === "human" ? "人工" : selectedNode.actorKind === "system" ? "系统" : members[1].name}</p><VButton variant="secondary" className="mt-4 w-full" onClick={() => setNotice(`${selectedNode.label}：已打开示例任务记录。`)}>查看任务记录</VButton></>}</section>
      : organizationVisible ? <section><Member member={members[selectedMember]} /><h3 className={`${sectionTitle} mt-5`}>职责</h3><p className="mt-2 text-[13px] leading-6 text-[var(--fg-secondary)]">{members[selectedMember].note}</p><VButton variant="secondary" className="mt-4 w-full" onClick={() => { setDirectMember(members[selectedMember]); setHomeMode("conversation"); setView("home"); }}>打开成员对话</VButton></section>
      : view === "home" ? <><section><h3 className={sectionTitle}>下一轮任务</h3><p className="mt-2 text-[13px] leading-6 text-[var(--fg-secondary)]">{topic}</p><VButton variant="primary" className="mt-4 w-full" icon={<Play size={14} />} isDisabled={scene !== "normal" || running} onClick={() => setDialog("start")}>{running ? "本轮正在运行" : "开始下一轮"}</VButton>{running && <VButton variant="secondary" className="mt-2 w-full" onClick={() => setRunning(false)}>停止示例运行</VButton>}</section><section className="border-t border-[var(--vui-border-subtle)] pt-5"><h3 className={sectionTitle}>上轮结果</h3><p className="mt-2 text-[13px] leading-6 text-[var(--fg-secondary)]">已确认 5 类布局差异，优先统一页面外框和标题栏。</p><p className={`${quiet} mt-2`}>结果已记录 · 今天 14:32</p></section></>
      : view === "sources" ? <><section><h3 className={sectionTitle}>{sources[selectedSource].title}</h3><p className="mt-3 text-[13px] leading-6 text-[var(--fg-secondary)]">{sources[selectedSource].description}</p><div className="mt-4"><VStatusChip tone="success">来源可追溯</VStatusChip></div></section><section className="border-t border-[var(--vui-border-subtle)] pt-5"><h3 className={sectionTitle}>核验要点</h3><p className="mt-2 text-[13px] leading-6 text-[var(--fg-secondary)]">对应到实际页面和组件，避免只凭样式名称判断统一程度。</p><VButton variant="secondary" className="mt-4 w-full" icon={<ArrowRight size={14} />} onClick={() => setNotice("资料查看操作已模拟。")}>查看资料</VButton></section></>
      : view === "experiment" ? <><section><h3 className={sectionTitle}>验证状态</h3><div className="mt-3"><VStatusChip tone={experimentDone ? "success" : "warning"}>{experimentDone ? "示例已完成" : "待执行"}</VStatusChip></div><VButton variant="primary" className="mt-4 w-full" icon={<Play size={14} />} isDisabled={scene !== "normal"} onClick={() => setExperimentDone(true)}>运行示例检查</VButton></section><section className="border-t border-[var(--vui-border-subtle)] pt-5"><h3 className={sectionTitle}>记录范围</h3><p className="mt-2 text-[13px] leading-6 text-[var(--fg-secondary)]">本预览只比较桌面布局，保留研究业务的阶段内容。</p></section></>
      : <><section><Member member={members[selectedMember]} /><h3 className={`${sectionTitle} mt-5`}>职责</h3><p className="mt-2 text-[13px] leading-6 text-[var(--fg-secondary)]">{members[selectedMember].note}</p><VButton variant="secondary" className="mt-4 w-full" icon={<MessageSquare size={14} />} onClick={() => { setDirectMember(members[selectedMember]); setHomeMode("conversation"); setView("home"); }}>打开成员对话</VButton></section><section className="border-t border-[var(--vui-border-subtle)] pt-5"><h3 className={sectionTitle}>会话配置</h3><p className={`${quiet} mt-2`}>沿用成员独立配置</p></section></>}
    <section className="border-t border-[var(--vui-border-subtle)] pt-5"><h3 className={sectionTitle}>团队信息</h3><div className="mt-3 flex items-center justify-between text-[12px] text-[var(--fg-secondary)]"><span>成员</span><span>3 位</span></div><div className="mt-3 flex items-center justify-between text-[12px] text-[var(--fg-secondary)]"><span>关联群聊</span><span>{team.name}群聊</span></div><VButton variant="ghost" density="compact" className="mt-4 w-full justify-start" icon={<Users size={14} />} onClick={() => setDialog("members")}>查看成员与设置</VButton></section>
  </div>;

  return <VuiProvider><div className="flex h-full min-h-0 flex-col bg-[var(--vui-surface-panel)] text-[var(--fg-primary)]">
    <div className="flex h-[38px] shrink-0 items-center gap-3 border-b border-[var(--vui-border-subtle)] bg-[var(--vui-surface-base)] px-4 text-[12px]" aria-label="预览控制栏"><strong className="font-medium">团队统一布局预览</strong><span className="text-[var(--fg-tertiary)]">桌面 · 示例数据</span><div className="ml-auto flex items-center gap-2"><label htmlFor="scene" className="shrink-0 whitespace-nowrap text-[var(--fg-tertiary)]">页面状态</label><VNativeSelect id="scene" aria-label="页面状态" value={scene} onChange={(event) => setScene(event.target.value as Scene)} className="w-[110px]" ><option value="normal">正常内容</option><option value="loading">加载中</option><option value="empty">暂无内容</option><option value="error">读取失败</option></VNativeSelect><VNativeSelect aria-label="主题" value={theme} onChange={(event) => setTheme(event.target.value)} className="w-[90px]" ><option value="light">浅色</option><option value="dark">深色</option></VNativeSelect></div></div>
    <div className="flex h-[48px] shrink-0 items-center gap-5 border-b border-[var(--vui-border-subtle)] bg-[var(--vui-surface-rail)] px-4"><strong className="text-[15px] font-medium tracking-tight">Vibelution</strong><span className="h-4 border-l border-[var(--vui-border-subtle)]" /><div className="flex items-center gap-1">{["会话", "Agent", "知识", "团队", "进化", "工具"].map((label) => <VButton key={label} variant="ghost" density="compact" aria-current={label === "团队" ? "page" : undefined} className={label === "团队" ? "aria-[current=page]:bg-[var(--vui-selection-bg)] font-medium" : "text-[var(--fg-tertiary)]"} onClick={() => label !== "团队" && setNotice("此预览仅展示团队页面。")}>{label}</VButton>)}</div><span className={`${quiet} ml-auto`}>本地项目 <ChevronRight size={12} className="mx-1 inline" /> Vibelution</span></div>
    <div className="min-h-0 flex-1"><TeamFrame fillBody={view === "home" || workflowVisible || organizationVisible} teamName={team.name} teamSwitcher={teamSwitcher} title={view === "home" && homeMode === "conversation" ? (directMember ? directMember.name + " · 对话" : "团队讨论") : current.label} navigation={navigation} inspectorTitle={workflowVisible ? "节点详情" : organizationVisible ? "成员详情" : view === "home" ? "本轮操作" : view === "sources" ? "资料详情" : view === "experiment" ? "实验操作" : "成员详情"} body={scene === "normal" ? ({ home: homeBody, sources: sourceView, experiment, organization, workflow }[view]) : stateView} inspector={inspector}
      toolbar={<>{view === "home" && <><VButton variant={homeMode === "canvas" ? "primary" : "ghost"} density="compact" aria-pressed={homeMode === "canvas"} onClick={() => setHomeMode("canvas")}>画布</VButton><VButton variant={homeMode === "conversation" ? "primary" : "ghost"} density="compact" aria-pressed={homeMode === "conversation"} onClick={() => { setDirectMember(null); setHomeMode("conversation"); }}>成员发言</VButton></>}<VButton variant="ghost" density="compact" icon={<RefreshCw size={14} />} onClick={() => { setScene("normal"); setNotice("示例内容已刷新。 "); }}>刷新</VButton><VButton variant="secondary" density="compact" icon={<MessageSquare size={14} />} onClick={() => { setDirectMember(null); setHomeMode("conversation"); setView("home"); }}>团队讨论</VButton></>} /></div>
    <footer className="flex h-7 shrink-0 items-center border-t border-[var(--vui-border-subtle)] px-4 text-[11px] text-[var(--fg-tertiary)]" role="status">{notice || "预览中的任务、发言与按钮反馈均为示例；不连接真实团队数据。"}<span className="ml-auto">布局一致，业务内容各自保留</span></footer>
    <VDialog open={dialog === "members"} onOpenChange={(open) => !open && setDialog(null)} title={`${team.name}成员`} description="示例成员配置，供布局预览" size="md"><div className="divide-y divide-[var(--vui-border-subtle)]">{members.map((member) => <div key={member.name} className="py-4"><Member member={member} /><p className="ml-[38px] mt-2 text-[13px] leading-6 text-[var(--fg-secondary)]">{member.note}</p></div>)}</div><div className="flex justify-end pt-4"><VButton variant="secondary" onClick={() => setDialog(null)}>关闭</VButton></div></VDialog>
    <VDialog open={dialog === "start"} onOpenChange={(open) => !open && setDialog(null)} title="开始下一轮" description="此操作只改变预览中的示例状态" size="md"><VTextarea aria-label="本轮任务" value={topic} rows={4} onChange={(event) => setTopic(event.target.value)} /><div className="flex justify-end gap-2 pt-4"><VButton variant="secondary" onClick={() => setDialog(null)}>取消</VButton><VButton variant="primary" isDisabled={!topic.trim()} onClick={() => { setRunning(true); setDialog(null); }}>开始示例运行</VButton></div></VDialog>
  </div></VuiProvider>;
}
