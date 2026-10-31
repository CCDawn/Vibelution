import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowLeft, ArrowRight, Globe, Maximize2, MessageCircle, PanelRightClose, PanelRightOpen, Plus, RotateCw, X } from "lucide-react";
import { browserState, launcherBrowserBridge, safeBrowserUrl, type BrowserOperation, type BrowserState } from "../../api/launcherAssistantBrowser";
import { PANE_RESIZE_HANDLE_WIDTH } from "../../components/layout/paneLayoutPersistence";
import { WORKBENCH_LAYOUT_IDS } from "../../components/layout/workbenchLayoutIds";
import { VButton, VIconButton, VInput, VSplitWorkspace } from "../../components/vui";
import { LauncherAssistantRoute } from "./LauncherAssistantRoute";
import styles from "./LauncherAssistantBrowserWorkspace.styles";

const empty: BrowserState = { pages: [], activePageId: null, takeover: false };
const chatMinWidth = 280;
const browserMinWidth = 360;

export function LauncherAssistantBrowserWorkspace() {
  const [state, setState] = useState<BrowserState>(empty);
  const [error, setError] = useState("");
  const [address, setAddress] = useState("");
  const [draft, setDraft] = useState(false);
  const [pending, setPending] = useState(false);
  const [full, setFull] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const [narrow, setNarrow] = useState(() => window.innerWidth <= 760);
  const [workspaceWidth, setWorkspaceWidth] = useState(() => window.innerWidth);
  const [mobilePage, setMobilePage] = useState<"chat" | "web">("web");
  const viewRef = useRef<HTMLDivElement>(null);
  const workspaceRef = useRef<HTMLDivElement>(null);
  const stateRevision = useRef(0);
  const ownerPending = useRef(false);
  const active = state.pages.find(page => page.id === state.activePageId);
  const webVisible = !collapsed && (!narrow || mobilePage === "web");
  const canShowPage = webVisible && !draft && Boolean(active);

  const run = useCallback(async (operation: BrowserOperation) => {
    setError("");
    const revision = stateRevision.current;
    try { const result = browserState(await launcherBrowserBridge().invoke(operation)); if (revision === stateRevision.current) setState(result); return result; }
    catch { setError("操作未完成，请检查网页地址或稍后重试。"); return null; }
  }, []);
  useEffect(() => {
    let live = true;
    try {
      const bridge = launcherBrowserBridge();
      const unsubscribe = bridge.onChanged(value => { if (!live) return; try { const next = browserState(value); stateRevision.current += 1; setState(next); } catch { setError("浏览器状态暂不可用，请重试。"); } });
      const revision = stateRevision.current;
      void bridge.invoke({ operation: "state" }).then(value => { if (live && revision === stateRevision.current) setState(browserState(value)); }).catch(() => { if (live) setError("浏览器状态暂不可用，请重试。"); });
      return () => { live = false; unsubscribe(); };
    } catch { setError("浏览器暂不可用，请稍后重试。"); }
  }, []);
  useEffect(() => {
    const bridge = window.vibelutionLauncherBrowser;
    if (typeof bridge?.onShow !== "function") return;
    return bridge.onShow(() => { setDraft(false); setCollapsed(false); setMobilePage("web"); });
  }, []);
  useEffect(() => { if (!draft) setAddress(active?.url ?? ""); }, [active?.id, active?.url, draft]);
  useEffect(() => { const resize = () => setNarrow(window.innerWidth <= 760); window.addEventListener("resize", resize); return () => window.removeEventListener("resize", resize); }, []);
  useEffect(() => {
    const node = workspaceRef.current;
    if (!node) return;
    const updateWidth = () => { const width = node.getBoundingClientRect().width; if (width > 0) setWorkspaceWidth(width); };
    updateWidth();
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(updateWidth);
    observer?.observe(node);
    window.addEventListener("resize", updateWidth);
    return () => { observer?.disconnect(); window.removeEventListener("resize", updateWidth); };
  }, []);
  useEffect(() => {
    let frame = 0;
    const publish = () => {
      const node = viewRef.current;
      const rect = node?.getBoundingClientRect();
      const overlay = document.querySelector('[data-vui="dialog-overlay"], [role="alertdialog"], [role="menu"], [role="listbox"]');
      const visible = canShowPage && !overlay && node && rect && rect.width > 0 && rect.height > 0
        && getComputedStyle(node).visibility !== "hidden" && getComputedStyle(node).display !== "none";
      const left = rect ? Math.max(0, Math.ceil(rect.left)) : 0;
      const top = rect ? Math.max(0, Math.ceil(rect.top)) : 0;
      const right = rect ? Math.min(window.innerWidth, Math.floor(rect.right)) : 0;
      const bottom = rect ? Math.min(window.innerHeight, Math.floor(rect.bottom)) : 0;
      const bounds = visible && right > left && bottom > top ? { x: left, y: top, width: right - left, height: bottom - top } : null;
      try { void launcherBrowserBridge().invoke({ operation: "bounds", bounds }).catch(() => {}); } catch { /* unavailable host */ }
    };
    const update = () => {
      cancelAnimationFrame(frame);
      if (document.visibilityState === "hidden") publish();
      else frame = requestAnimationFrame(publish);
    };
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(update);
    // Native views sit above the DOM. Hide them while VUI portal overlays are open.
    const overlays = new MutationObserver(update);
    overlays.observe(document.body, { childList: true, subtree: true });
    if (viewRef.current) observer?.observe(viewRef.current);
    window.addEventListener("resize", update); window.addEventListener("scroll", update, true); document.addEventListener("visibilitychange", update); update();
    return () => { cancelAnimationFrame(frame); observer?.disconnect(); overlays.disconnect(); window.removeEventListener("resize", update); window.removeEventListener("scroll", update, true); document.removeEventListener("visibilitychange", update);
      try { void launcherBrowserBridge().invoke({ operation: "bounds", bounds: null }).catch(() => {}); } catch { /* unavailable host */ } };
  }, [canShowPage]);
  async function go(value = address) {
    let url: string;
    try { url = safeBrowserUrl(value); } catch { setError("请输入不含用户名和密码、长度不超过 8192 的完整 http 或 https 网页地址。"); return; }
    const result = await run(draft || !active ? { operation: "open", url } : { operation: "navigate", pageId: active.id, url });
    if (result) { setDraft(false); setMobilePage("web"); }
  }
  async function changeOwner() {
    if (ownerPending.current) return;
    ownerPending.current = true; setPending(true);
    try { await run({ operation: state.takeover ? "resume" : "takeover" }); } finally { ownerPending.current = false; setPending(false); }
  }
  const browser = <section className={styles.browser} aria-label="浏览器">
    <header className={styles.header}>
      <span className={styles.heading}><Globe size={16} />网页</span>
      <div className={styles.controls}><span className={styles.ownership}>{state.takeover ? "你正在操作" : "助理可操作"}</span>
        <VButton isPending={pending} onClick={() => void changeOwner()}>{state.takeover ? "交给助理" : pending ? "等待当前操作" : "接手"}</VButton>
        <VButton variant="ghost" isIconOnly className={styles.icon} aria-label={full ? "回到对话" : "展开网页"} onClick={() => { setFull(!full); if (full && narrow) setMobilePage("chat"); }}>
          {full ? <MessageCircle size={16} /> : <Maximize2 size={16} />}</VButton>
        <VIconButton variant="ghost" className={styles.icon} label="收起网页" title="收起网页" icon={<PanelRightClose size={16} />} onClick={() => { setFull(false); setCollapsed(true); setMobilePage("chat"); }} /></div>
    </header>
    <div className={styles.tabs} aria-label="网页标签">
      {state.pages.map(page => <div key={page.id} className={`${styles.pageTab} ${page.id === state.activePageId && !draft ? styles.pageTabActive : ""}`}>
        <VButton variant="ghost" className={styles.pageTabButton} aria-pressed={page.id === state.activePageId && !draft} onClick={() => { setDraft(false); void run({ operation: "select", pageId: page.id }); }}>{page.title || page.url || "网页"}</VButton>
        <VButton variant="ghost" isIconOnly className={styles.icon} aria-label={`关闭 ${page.title || "网页"}`} onClick={() => void run({ operation: "close", pageId: page.id })}><X size={13} /></VButton>
      </div>)}
      <VButton variant="ghost" isIconOnly className={styles.icon} aria-label="新建网页" isDisabled={state.pages.length >= 4} onClick={() => { setDraft(true); setAddress(""); setError(""); }}><Plus size={16} /></VButton>
    </div>
    <form className={styles.addressBar} onSubmit={event => { event.preventDefault(); void go(); }}>
      <VButton type="button" variant="ghost" isIconOnly className={styles.icon} aria-label="后退" isDisabled={!active || draft || !active.canGoBack} onClick={() => active && void run({ operation: "back", pageId: active.id })}><ArrowLeft size={16} /></VButton>
      <VButton type="button" variant="ghost" isIconOnly className={styles.icon} aria-label="前进" isDisabled={!active || draft || !active.canGoForward} onClick={() => active && void run({ operation: "forward", pageId: active.id })}><ArrowRight size={16} /></VButton>
      <VButton type="button" variant="ghost" isIconOnly className={styles.icon} aria-label="刷新" isDisabled={!active || draft} onClick={() => active && void run({ operation: "reload", pageId: active.id })}><RotateCw size={16} /></VButton>
      <VInput className={styles.addressInput} aria-label="网页地址" value={address} placeholder="输入 http 或 https 网页地址" onChange={event => setAddress(event.target.value)} />
      <VButton type="submit">打开</VButton>
    </form>
    {error || active?.loadError ? <p role="alert" className={styles.error}>{error || "网页加载失败，请检查地址后重试。"}</p> : null}
    {active?.loading && !draft ? <div role="progressbar" aria-label="网页加载中" className={styles.progress} /> : null}
    <div className={styles.viewportContainer}>
      {(!active || draft) ? <div className={styles.empty}><Globe size={28} /><p>输入网页地址，或从这里开始浏览。</p><VButton onClick={() => void go("https://www.bilibili.com/")}>打开哔哩哔哩</VButton></div> : null}
      <div ref={viewRef} data-launcher-browser-viewport="true" className={canShowPage ? styles.viewport : styles.viewportHidden} />
    </div>
  </section>;
  return <div ref={workspaceRef} className={styles.root} data-vui-domain-recipe="launcher-assistant-browser">
    {narrow ? <div className={styles.mobileSwitch}><VButton variant={!webVisible ? "secondary" : "ghost"} aria-pressed={!webVisible} onClick={() => { setFull(false); setMobilePage("chat"); }}>对话</VButton><VButton variant={webVisible ? "secondary" : "ghost"} aria-pressed={webVisible} onClick={() => { setCollapsed(false); setMobilePage("web"); }}>网页</VButton></div> : null}
    {collapsed && !narrow ? <VIconButton variant="ghost" className={styles.restore} label="打开网页" title="打开网页" icon={<PanelRightOpen size={16} />} onClick={() => { setCollapsed(false); setMobilePage("web"); }} /> : null}
    <VSplitWorkspace className={`${styles.split} ${!webVisible ? styles.chatOnly : narrow || full ? styles.webOnly : ""}`} resize={{ layoutId: WORKBENCH_LAYOUT_IDS.launcherAssistantBrowser, sidebar: { defaultWidth: 360, minWidth: chatMinWidth, maxWidth: Math.max(chatMinWidth, Math.floor(workspaceWidth - browserMinWidth - PANE_RESIZE_HANDLE_WIDTH)) } }}
      sidebar={<LauncherAssistantRoute embedded navigationOwned />}
      main={browser} />
  </div>;
}
