import { useEffect, useState } from "react";
import { ArrowUpRight, Boxes, ChevronDown, Code2, GitBranch, Hash, Menu, MessageSquare, Users } from "lucide-react";
import { VButton, VDialog, VIconButton, VNativeSelect, VSessionWorkbenchPage, VuiProvider } from "../../../src/components/vui";
import { WORKBENCH_LAYOUT_IDS } from "../../../src/components/layout/workbenchLayoutIds";
import { GroupPreview } from "./GroupPreview";
import { TeamPreview } from "./TeamPreview";
import { MemberList, styles, usePreviewDialogFocus } from "./PreviewUi";
import { sceneLabels, type PreviewScene, type PreviewView } from "./fixtures";

function readInitialState() {
  const params = new URLSearchParams(location.search);
  const scene = params.get("scene") ?? "running";
  return { view: params.get("view") === "chat" ? "chat" as const : "team" as const, scene: scene in sceneLabels ? scene as PreviewScene : "running" as const };
}

const drawerClasses = "!left-auto !right-0 !top-0 !h-[100dvh] !max-h-[100dvh] !w-[min(100%,380px)] !translate-x-0 !translate-y-0 !rounded-none [&_[data-slot=dialog-header]]:px-5 [&_[data-slot=dialog-header]]:py-4 [&_[data-slot=dialog-body]]:px-5";

export function TeamChatPreview() {
  const initial = readInitialState();
  const [view, setView] = useState<PreviewView>(initial.view);
  const [scene, setScene] = useState<PreviewScene>(initial.scene);
  const [drawer, setDrawer] = useState<"members" | "navigation" | "structure" | null>(null);
  const [revision, setRevision] = useState(0);
  const drawerFocus = usePreviewDialogFocus();
  const openDrawer = (next: typeof drawer) => { if (drawer === null && next !== null) drawerFocus.remember(); setDrawer(next); };

  useEffect(() => {
    const params = new URLSearchParams({ view, scene });
    history.replaceState(null, "", `${location.pathname}?${params}`);
  }, [view, scene]);

  const navigate = (next: PreviewView) => { setView(next); setDrawer(null); };
  const navigation = <nav aria-label="团队导航" className="flex h-full min-w-0 flex-col bg-[var(--vui-surface-rail)] px-4 py-5">
    <VButton variant="ghost" className={`${styles.quietButton} !justify-start !px-1 !text-[14px] !font-semibold ${styles.touch}`} icon={<Code2 size={17} />} trailingIcon={<ChevronDown size={14} />} onClick={() => openDrawer("members")}>开发团队</VButton>
    <div className="mt-7 grid gap-1">
      <VButton variant="ghost" aria-current={view === "team" ? "page" : undefined} className={`!justify-start !rounded-lg !px-3 !text-[14px] ${styles.touch} ${view === "team" ? "!bg-[var(--vui-control-muted)] !font-semibold !text-[var(--fg-primary)]" : styles.quietButton}`} icon={<Boxes size={16} />} onClick={() => navigate("team")}>团队工作台</VButton>
      <VButton variant="ghost" aria-current={view === "chat" ? "page" : undefined} className={`!justify-start !rounded-lg !px-3 !text-[14px] ${styles.touch} ${view === "chat" ? "!bg-[var(--vui-control-muted)] !font-semibold !text-[var(--fg-primary)]" : styles.quietButton}`} icon={<MessageSquare size={16} />} onClick={() => navigate("chat")}>团队群聊</VButton>
    </div>
    <p className="mb-2 mt-8 px-3 text-[11px] font-medium tracking-wider text-[var(--fg-tertiary)]">最近任务</p>
    <VButton variant="ghost" className={`${styles.quietButton} ${styles.touch} !h-auto !justify-start !px-3 !py-3 !text-left !text-[13px]`} icon={<Hash size={14} />} onClick={() => navigate("chat")}>登录流程优化</VButton>
    <div className="mt-auto border-t border-[var(--vui-border-subtle)] pt-4">
      <VButton variant="ghost" className={`${styles.quietButton} ${styles.touch} !w-full !justify-start !px-3 !text-[13px]`} icon={<GitBranch size={15} />} onClick={() => openDrawer("structure")}>组织结构</VButton>
      <VButton variant="ghost" className={`${styles.quietButton} ${styles.touch} !w-full !justify-start !px-3 !text-[13px]`} icon={<Users size={15} />} onClick={() => openDrawer("members")}>团队成员</VButton>
    </div>
  </nav>;

  return <VuiProvider><div className="flex h-[100dvh] min-h-0 min-w-0 flex-col bg-[var(--vui-surface-panel)] text-[var(--fg-primary)]">
    <div className="flex min-h-9 shrink-0 flex-wrap items-center justify-between gap-2 border-b border-[var(--vui-border-subtle)] bg-[var(--vui-surface-rail)] px-5 py-1.5 text-[11px] max-[600px]:px-3" aria-label="预览控制">
      <span className="flex items-center gap-2 font-medium text-[var(--fg-tertiary)]"><span className="h-1.5 w-1.5 rounded-full bg-amber-500" />设计预览 · 模拟数据</span>
      <div className="flex items-center gap-2"><label htmlFor="preview-scene" className="text-[var(--fg-tertiary)]">场景</label><VNativeSelect id="preview-scene" aria-label="预览场景" className="!h-7 !min-h-7 !w-24 !py-0 !text-xs max-[600px]:!min-h-11" value={scene} onChange={(event) => { setScene(event.target.value as PreviewScene); setRevision((value) => value + 1); }}>{Object.entries(sceneLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</VNativeSelect><VButton variant="ghost" className="!h-7 !min-h-7 !text-[11px] max-[600px]:!min-h-11" onClick={() => setRevision((value) => value + 1)}>重置</VButton></div>
    </div>
    <header className="flex h-14 shrink-0 items-center justify-between border-b border-[var(--vui-border-subtle)] px-5 max-[600px]:px-3">
      <div className="flex min-w-0 items-center gap-7 max-[850px]:gap-3"><div className="flex items-center gap-2.5"><span className="inline-flex h-7 w-7 items-center justify-center rounded-lg bg-[var(--fg-primary)] text-white"><Boxes size={17} /></span><span className="text-[15px] font-semibold tracking-tight max-[600px]:hidden">Vibelution</span></div><nav className="flex gap-1" aria-label="工作区"><VButton variant="ghost" className={`${styles.quietButton} !text-sm ${styles.touch} ${view === "chat" ? "!bg-[var(--vui-control-muted)] !font-semibold" : ""}`} onClick={() => navigate("chat")}>对话</VButton><VButton variant="ghost" className={`${styles.quietButton} !text-sm ${styles.touch} ${view === "team" ? "!bg-[var(--vui-control-muted)] !font-semibold" : ""}`} onClick={() => navigate("team")}>团队</VButton></nav></div>
      <div className="flex items-center gap-3"><span className="text-xs text-[var(--fg-tertiary)] max-[600px]:hidden">本地工作区</span><VIconButton label="打开团队导航" icon={<Menu size={19} />} variant="ghost" className="!h-11 !w-11 min-[851px]:!hidden" onClick={() => openDrawer("navigation")} /><span className="inline-flex h-8 w-8 items-center justify-center rounded-full bg-[var(--vui-control-muted)] text-xs font-semibold max-[600px]:hidden" aria-label="当前用户">你</span></div>
    </header>
    <VSessionWorkbenchPage ariaLabel="团队与群聊预览" layoutId={WORKBENCH_LAYOUT_IDS.teams} domainRecipe="team-chat-isolated-preview" hostClassName="grid min-h-0 flex-1 !grid-cols-[232px_minmax(0,1fr)] !gap-0 max-[850px]:!grid-cols-[minmax(0,1fr)]" indexRail={<aside className="col-start-1 row-start-1 min-h-0 border-r border-[var(--vui-border-subtle)] max-[850px]:hidden">{navigation}</aside>} session={<main className="col-start-2 row-start-1 flex min-h-0 min-w-0 flex-col overflow-hidden max-[850px]:col-start-1" key={`${scene}:${revision}`}>
      {view === "team" ? <TeamPreview scene={scene} onChat={() => navigate("chat")} onMembers={() => openDrawer("members")} /> : <GroupPreview scene={scene} onMembers={() => openDrawer("members")} onTeam={() => navigate("team")} />}
    </main>} />
    <VDialog onCloseAutoFocus={drawerFocus.onCloseAutoFocus} open={drawer !== null} onOpenChange={(open) => { if (!open) setDrawer(null); }} title={drawer === "navigation" ? "团队导航" : drawer === "structure" ? "组织结构" : "团队成员"} contentClassName={drawerClasses}>
      {drawer === "navigation" ? <div className="h-[calc(100dvh_-_100px)]">{navigation}</div> : drawer === "members" ? <MemberList /> : <div className="py-4"><div className="flex items-center gap-2 text-sm font-semibold"><GitBranch size={16} />开发团队</div><ol className="mt-6 grid gap-6 border-l border-[var(--vui-border-subtle)] pl-5"><li><p className="text-sm font-semibold">规划师</p><p className="mt-1 text-xs text-[var(--fg-tertiary)]">拆分任务与分派负责人</p></li><li><p className="text-sm font-semibold">开发工程师 A · 开发工程师 B</p><p className="mt-1 text-xs text-[var(--fg-tertiary)]">并行实现，提交产出</p></li><li><p className="text-sm font-semibold">评审员</p><p className="mt-1 text-xs text-[var(--fg-tertiary)]">独立核对验收条件</p></li></ol><VButton className={`mt-7 ${styles.touch}`} variant="secondary" icon={<ArrowUpRight size={14} />} onClick={() => navigate("team")}>返回团队工作台</VButton></div>}
    </VDialog>
  </div></VuiProvider>;
}
