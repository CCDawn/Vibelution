/** Isolated proposal: fixtures only; no Launcher bridge, API or real update actions. */
import { StrictMode, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { ArrowUpCircle, Check, ChevronDown, Info, LoaderCircle, RefreshCw, TriangleAlert } from "lucide-react";
import { VButton, VPage, VStringSelect, VuiProvider } from "../../src/components/vui";
import "../../src/design/tokens.css";
import "../../src/design/base.css";
import "../../src/design/tailwind.css";
import "../../src/design/vui-provider-theme.css";
import "./preview.css";

type Scene = "available" | "current" | "not-built" | "unknown" | "error" | "preparing";
const scenes: { value: Scene; label: string }[] = [
  { value: "available", label: "发现更新" },
  { value: "current", label: "已是最新" },
  { value: "not-built", label: "尚未构建" },
  { value: "unknown", label: "版本未知" },
  { value: "error", label: "更新失败" },
  { value: "preparing", label: "准备更新" },
];
const copy: Record<Scene, { title: string; description: string }> = {
  available: { title: "发现更新", description: "有新的 Launcher 构建可用。看看这次有哪些变化。" },
  current: { title: "已是最新版本", description: "当前运行的 Launcher 已与最新可用构建一致。" },
  "not-built": { title: "更新尚未构建", description: "本地代码有变化，但还没有可安装的 Launcher 构建。" },
  unknown: { title: "暂时无法确认版本", description: "未取得可信的构建信息，请重新检测后再更新。" },
  error: { title: "更新未完成", description: "当前版本仍可使用。你可以重试更新，或先重新检测。" },
  preparing: { title: "正在准备更新", description: "保存已有任务记录并准备新构建，完成后将重启 Launcher。" },
};
// These are wording examples, deliberately not attributed to any real build or commit.
const exampleChanges = [
  { title: "任务清理失败时，告诉你原因和下一步怎么处理", detail: "减少只显示“失败”、不知道如何继续的情况。" },
  { title: "修复助理回复中途停止的问题", detail: "让对话更连贯，减少需要重复发送的情况。" },
  { title: "更新后，更准确地显示正在使用的版本", detail: "避免已经更新，页面却仍提示有新版本。" },
];
const exampleCommits = [
  { id: "example-01", subject: "fix(cleanup): explain cleanup failures and recovery steps" },
  { id: "example-02", subject: "fix(assistant): keep response stream active until completion" },
  { id: "example-03", subject: "fix(launcher): identify the running build from its manifest" },
  { id: "example-04", subject: "test(launcher): cover missing build identity" },
];

function LauncherBuildUpdatePreview() {
  const initialScene = new URLSearchParams(window.location.search).get("scene");
  const [scene, setScene] = useState<Scene>(() => scenes.find((item) => item.value === initialScene)?.value ?? "available");
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [checking, setChecking] = useState(false);
  const [notice, setNotice] = useState("");
  const timer = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(timer.current), []);
  const preparing = scene === "preparing";
  const hasNotes = scene === "available" || scene === "error" || preparing;
  const canUpdate = scene === "available" || scene === "error" || scene === "not-built";
  const status = copy[scene];
  const Icon = preparing ? LoaderCircle : scene === "current" ? Check
    : scene === "error" ? TriangleAlert : scene === "unknown" || scene === "not-built" ? Info : ArrowUpCircle;

  function changeScene(value: string) {
    window.clearTimeout(timer.current);
    setScene(value as Scene);
    setChecking(false);
    setNotice("");
    setDetailsOpen(false);
    const url = new URL(window.location.href);
    url.searchParams.set("scene", value);
    window.history.replaceState(null, "", url);
  }

  function simulateCheck() {
    setChecking(true);
    setNotice("正在模拟检测…");
    timer.current = window.setTimeout(() => {
      setChecking(false);
      setNotice("模拟检测完成，当前场景保持不变。未连接真实版本服务。");
    }, 850);
  }

  function simulateUpdate() {
    setScene("preparing");
    setNotice("已模拟更新请求；不会安装构建、停止任务或重启窗口。");
    timer.current = window.setTimeout(() => {
      setScene("current");
      setNotice("模拟更新完成。真实 Launcher 和任务均未改变。");
    }, 1800);
  }

  return <VuiProvider>
    <div className="preview-layout">
      <main className="preview-main">
        <VPage ariaLabel="Launcher 更新预览" className="update-page" data-scene={scene}>
          <div className="preview-caption"><span>Launcher 更新</span><span className="preview-label">界面预览 · 示例数据</span></div>
          <header className="update-heading">
            <span className={`status-icon status-icon--${scene}`}><Icon size={20} aria-hidden="true" className={preparing ? "preparing-icon" : undefined} /></span>
            <div>
              <h1>{status.title}</h1>
              <p className="update-description">{status.description}</p>
            </div>
          </header>

          {hasNotes ? <section className="changes-section" aria-labelledby="changes-title">
            <div className="section-heading"><h2 id="changes-title">本次更新</h2><span>3 项变化</span></div>
            <p className="example-note">以下为文案示例，未连接真实更新记录。</p>
            <ul className="change-list">
              {exampleChanges.map((item) => <li key={item.title}>
                <span className="change-dot" aria-hidden="true" />
                <div><p className="change-title">{item.title}</p><p className="change-detail">{item.detail}</p></div>
              </li>)}
            </ul>
          </section> : <section className="empty-update" aria-label="更新内容">
            <h2>{scene === "current" ? "暂无新的更新内容" : "暂不显示更新内容"}</h2>
            <p>{scene === "current" ? "有新构建时，会在这里列出主要变化。"
              : scene === "not-built" ? "可安装构建生成后，再核对本次更新的准确范围。"
                : "没有可信的构建起点，无法准确判断本次变化。"}</p>
          </section>}

          {scene === "error" ? <p className="update-error" role="alert">示例错误：新构建未通过启动检查，尚未替换当前版本。</p> : null}
          <div className="update-actions">
            {canUpdate || preparing ? <VButton variant="primary" density="normal" className="preview-action" isPending={preparing} isDisabled={preparing || checking} icon={<ArrowUpCircle size={15} aria-hidden="true" />} onPress={simulateUpdate}>
              {preparing ? "准备中…" : scene === "error" ? "重试更新并重启" : scene === "not-built" ? "构建并更新" : "更新并重启"}
            </VButton> : null}
            <VButton variant={canUpdate || preparing ? "secondary" : "primary"} density="normal" className="preview-action" isPending={checking} isDisabled={preparing} icon={<RefreshCw size={14} aria-hidden="true" />} onPress={simulateCheck}>重新检测</VButton>
          </div>
          {canUpdate || preparing ? <p className="restart-note">更新会中断进行中的任务并保存已有记录，重启后可回到会话继续。</p> : null}
          <p className="action-feedback" role="status" aria-live="polite">{notice}</p>

          <section className="build-details">
            <VButton variant="ghost" className="details-toggle" aria-expanded={detailsOpen} aria-controls="build-details-content" onPress={() => setDetailsOpen((open) => !open)} trailingIcon={<ChevronDown size={14} aria-hidden="true" className={detailsOpen ? "details-chevron is-open" : "details-chevron"} />}>构建信息与完整提交记录</VButton>
            {detailsOpen ? <div id="build-details-content" className="details-content">
              <p className="example-note">以下构建标识与提交均为示例，不代表真实版本。</p>
              <dl className="build-versions">
                <dt>当前运行构建</dt><dd>{scene === "unknown" ? "未知" : scene === "current" ? "example-build-002" : "example-build-001"}</dd>
                <dt>最新可用构建</dt><dd>{scene === "unknown" ? "未知" : scene === "not-built" ? "尚无可用构建" : "example-build-002"}</dd>
                <dt>更新范围</dt><dd>{scene === "unknown" || scene === "not-built" ? "暂时无法确定" : scene === "current" ? "无待更新内容" : "example-build-001 → example-build-002"}</dd>
              </dl>
              {hasNotes ? <div className="commit-section"><h3>完整提交记录 <span>示例 · 4 条</span></h3><ul className="commit-list">
                {exampleCommits.map((commit) => <li key={commit.id}><code>{commit.id}</code><span>{commit.subject}</span></li>)}
              </ul></div> : <p className="no-commits">{scene === "current" ? "没有待更新的提交记录。" : "构建范围确认前，不展示推测的提交记录。"}</p>}
            </div> : null}
          </section>
        </VPage>
      </main>
      <footer className="preview-controls" aria-label="预览场景控制">
        <label htmlFor="preview-scene">预览场景</label>
        <VStringSelect id="preview-scene" ariaLabel="选择预览场景" value={scene} options={scenes} onValueChange={changeScene} className="scene-select" />
        <p>仅模拟界面与操作反馈</p>
      </footer>
    </div>
  </VuiProvider>;
}

createRoot(document.getElementById("root")!).render(<StrictMode><LauncherBuildUpdatePreview /></StrictMode>);
