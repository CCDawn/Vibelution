import { StrictMode, useState } from "react";
import { createRoot } from "react-dom/client";
import { LauncherUpdateTopbarView } from "../../src/app/LauncherUpdateTopbar";
import { VButton, VCheckbox, VDenseOpsPage, VDenseTable, VStringSelect, VToolbar, VuiProvider, type VDenseTableColumn } from "../../src/components/vui";
import { LauncherStartupSettingsPanel } from "../../src/routes/LauncherStartupSettingsPanel";
import "./preview.css";

type Scene = "available" | "active" | "building" | "error" | "current" | "unknown";
const scenes: { value: Scene; label: string }[] = [
  { value: "available", label: "有新版本" }, { value: "active", label: "有任务进行中" },
  { value: "building", label: "更新构建中" }, { value: "error", label: "更新失败" },
  { value: "current", label: "已经是最新" }, { value: "unknown", label: "检测失败" },
];
const startupCopy = {
  startupSettings: "启动设置", expandSettings: "展开编辑", collapseSettings: "收起编辑",
  runtimeProfile: "运行模式", windowMode: "窗口模式", windowModeFullscreen: "全屏", windowModeWindowed: "窗口化",
  windowSize: "窗口大小", windowSizeAuto: "自动", windowSizeEnvOverride: "窗口大小由环境变量覆盖",
  interfaceLanguage: "界面语言", languageZh: "中文", languageEn: "English", preflightDoctor: "启动检查",
  requireVenv: "检查虚拟环境", saveStartupSettings: "保存设置",
};
type Row = { branch: string; current: boolean; open: boolean };
const rows: Row[] = [{ branch: "main", current: true, open: true }, { branch: "codex/chat-flow", current: false, open: false }];
const compact = "!min-h-8 !px-3 !text-vui-xs max-[600px]:!min-h-11";

function LauncherUpdatePreview() {
  const [scene, setScene] = useState<Scene>(() => scenes.find((item) => item.value === new URLSearchParams(window.location.search).get("scene"))?.value ?? "available");
  const [notice, setNotice] = useState("");
  const [dark, setDark] = useState(false);
  const columns: VDenseTableColumn<Row>[] = [
    { id: "branch", header: "分支", fill: true, minWidth: 180, render: (row) => <strong className="font-medium">{row.branch}</strong> },
    { id: "state", header: "状态", width: 130, render: (row) => <span className={row.open ? "text-[var(--state-success)]" : "text-vui-fg-secondary"}>{row.open ? "● 正常运行" : "○ 可以启动"}</span> },
    { id: "window", header: "WORKBENCH 窗口", width: 170, render: (row) => <span className="text-vui-fg-secondary">{row.current ? "main" : "chat-flow"} 台 · {row.open ? "已打开" : "未打开"}</span> },
    { id: "git", header: "GIT", width: 80, render: () => <span className="text-vui-fg-secondary">干净</span> },
    { id: "actions", header: "操作", width: 180, align: "right", render: (row) => <VButton variant={row.open ? "secondary" : "primary"} className={compact} onPress={() => setNotice("这是隔离预览，不会打开或停止真实工作区。")}>{row.open ? "聚焦窗口" : "打开窗口"}</VButton> },
  ];
  return <VuiProvider>
    <div className="grid min-h-dvh grid-rows-[auto_1fr_auto] bg-vui-surface-workspace text-vui-fg-primary" data-theme={dark ? "dark" : "light"}>
      <LauncherUpdateTopbarView lang="zh" branchName="main" checking={false} checkFailed={scene === "unknown"} updating={scene === "building"}
        freshness={{ current: scene === "current" ? true : scene === "unknown" ? null : false, label: "sample", updateAvailable: scene !== "current" && scene !== "unknown", runningShort: "5f55d1b", headShort: "269d95c", activeWorkState: scene === "active" ? "active" : scene === "unknown" ? "unknown" : "idle", activeWorkCount: scene === "active" ? 1 : 0 }}
        error={scene === "error" ? "构建未通过，尚未替换当前版本。可重新检测或重试。" : undefined}
        onCheck={() => { setScene("current"); setNotice("模拟检测已完成；未请求真实版本服务。"); }}
        onUpdate={() => setScene("building")} />
      <VDenseOpsPage hideHeader fill={false} ariaLabel="Launcher 主界面" className="min-w-0" bodyClassName="gap-3 p-3 max-[600px]:p-2">
        <LauncherStartupSettingsPanel copy={startupCopy} uiLang="zh" setting={undefined} configuredWindowMode="windowed" effectiveWindowModeLabel="窗口化" windowModeDetail="" pending={false} pendingWindowMode="" onSave={() => setNotice("预览不会保存真实设置。")} onWindowModeChange={() => setNotice("预览不会调整真实窗口。")} />
        <section className="min-w-0 rounded-[var(--vui-radius-panel-soft)] border border-vui-border-subtle bg-vui-surface-panel p-3">
          <div className="mb-3 flex min-w-0 flex-wrap items-center justify-between gap-2"><strong className="text-vui-sm font-medium">分支实例</strong><VButton className={compact} variant="ghost" onPress={() => setNotice("工具页不在本次预览范围内。")}>工具与诊断</VButton></div>
          <VDenseTable ariaLabel="分支实例预览" rows={rows} getRowKey={(row) => row.branch} columns={columns} className="min-w-0 overflow-x-auto text-vui-xs" />
        </section>
        {notice ? <p className="m-0 px-2 text-vui-xs text-vui-fg-secondary" role="status">{notice}</p> : null}
      </VDenseOpsPage>
      <VToolbar ariaLabel="预览场景控制" className="gap-3 border-t border-vui-border-subtle bg-vui-surface-panel px-4 py-3 max-[600px]:px-3">
        <span className="text-vui-xs text-vui-fg-tertiary">正式组件 · 隔离模拟</span>
        <VStringSelect ariaLabel="预览状态" value={scene} options={scenes} onValueChange={(value) => setScene(value as Scene)} className="w-40" />
        <VCheckbox isSelected={dark} onChange={(value) => { setDark(value); document.documentElement.dataset.theme = value ? "dark" : "light"; }}>深色</VCheckbox>
        <span className="ml-auto text-vui-xs text-vui-fg-tertiary">与本地代码比较，未检测远端发布</span>
      </VToolbar>
    </div>
  </VuiProvider>;
}
createRoot(document.getElementById("root")!).render(<StrictMode><LauncherUpdatePreview /></StrictMode>);
