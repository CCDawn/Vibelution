import { useCallback, useEffect, useRef, useState, type ComponentProps } from "react";
import { ArrowLeft, ArrowRight, Globe, Maximize2, MessageCircle, PanelRightClose, Plus, RotateCw, X } from "lucide-react";
import { browserState, launcherBrowserBridge, safeBrowserUrl, type BrowserOperation, type BrowserState } from "../../api/launcherAssistantBrowser";
import type { LauncherControlContinuation } from "./useLauncherControlContinuation";
import { PANE_RESIZE_HANDLE_WIDTH } from "../../components/layout/paneLayoutPersistence";
import { WORKBENCH_LAYOUT_IDS } from "../../components/layout/workbenchLayoutIds";
import { useShellI18n } from "../../i18n/useShellI18n";
import { VButton, VIconButton, VInput, VSplitWorkspace } from "../../components/vui";
import { LauncherAssistantRoute } from "./LauncherAssistantRoute";
import styles from "./LauncherAssistantBrowserWorkspace.styles";

const COPY = {
  zh: {
    browser: "浏览器", web: "网页", webPage: "网页", tabs: "网页标签", closeTab: "关闭",
    ownedByUser: "你正在操作", ownedByAssistant: "助理可操作",
    takeOver: "接手", handOff: "交给助理并继续", waiting: "等待当前操作",
    backToChat: "回到对话", expandWeb: "展开网页", collapseWeb: "收起网页",
    newPage: "新建网页", back: "后退", forward: "前进", reload: "刷新",
    address: "网页地址", addressPlaceholder: "输入网址", open: "打开",
    emptyHint: "打开网页", openPage: "打开网页", bilibili: "哔哩哔哩", chat: "对话",
    loading: "网页加载中", loadFailed: "网页加载失败，请检查地址后重试。",
    invalidAddress: "请输入不含用户名和密码、长度不超过 8192 的完整 http 或 https 网页地址。",
    operationFailed: "操作未完成，请检查网页地址或稍后重试。",
    stateUnavailable: "浏览器状态暂不可用，请重试。", browserUnavailable: "浏览器暂不可用，请稍后重试。",
  },
  en: {
    browser: "Browser", web: "Web", webPage: "Web page", tabs: "Web tabs", closeTab: "Close",
    ownedByUser: "You're in control", ownedByAssistant: "Assistant is in control",
    takeOver: "Take over", handOff: "Hand off and continue", waiting: "Waiting for the current action",
    backToChat: "Back to conversation", expandWeb: "Expand web page", collapseWeb: "Collapse web page",
    newPage: "New web page", back: "Back", forward: "Forward", reload: "Reload",
    address: "Web address", addressPlaceholder: "Enter a URL", open: "Open",
    emptyHint: "Open a web page", openPage: "Open web page", bilibili: "Bilibili", chat: "Chat",
    loading: "Page loading", loadFailed: "The page failed to load. Check the address and try again.",
    invalidAddress: "Enter a complete http or https address without a username or password, at most 8192 characters long.",
    operationFailed: "The action didn't finish. Check the web address or try again later.",
    stateUnavailable: "Browser state is unavailable. Try again.", browserUnavailable: "The browser is unavailable. Try again later.",
  },
} as const;

const empty: BrowserState = { pages: [], activePageId: null, takeover: false };
const chatMinWidth = 280;
const browserMinWidth = 360;

export function LauncherAssistantBrowserWorkspace({ revealRequested = false, assistantProps }: {
  revealRequested?: boolean;
  assistantProps?: Pick<ComponentProps<typeof LauncherAssistantRoute>, "computerRequested" | "entryIntent">;
}) {
  const { lang } = useShellI18n();
  const copy = COPY[lang];
  const [state, setState] = useState<BrowserState>(empty);
  const [error, setError] = useState("");
  const [address, setAddress] = useState("");
  const [draft, setDraft] = useState(false);
  const [pending, setPending] = useState(false);
  const [full, setFull] = useState(false);
  const [collapsed, setCollapsed] = useState(!revealRequested);
  const [narrow, setNarrow] = useState(() => window.innerWidth <= 760);
  const [workspaceWidth, setWorkspaceWidth] = useState(() => window.innerWidth);
  const [mobilePage, setMobilePage] = useState<"chat" | "web">("web");
  const viewRef = useRef<HTMLDivElement>(null);
  const workspaceRef = useRef<HTMLDivElement>(null);
  const stateRevision = useRef(0);
  const ownerPending = useRef(false);
  const currentState = useRef(state);
  const continuation = useRef<LauncherControlContinuation | null>(null);
  const bindContinuation = useCallback((control: LauncherControlContinuation | null) => { continuation.current = control; }, []);
  const active = state.pages.find(page => page.id === state.activePageId);
  const webVisible = !collapsed && (!narrow || mobilePage === "web");
  const canShowPage = webVisible && !draft && Boolean(active);

  // Legacy browser URLs and native Agent requests reveal the same pane. The
  // conversation stays mounted as the location/search changes.
  useEffect(() => {
    if (revealRequested) { setDraft(false); setCollapsed(false); setMobilePage("web"); }
  }, [revealRequested]);

  const run = useCallback(async (operation: BrowserOperation) => {
    setError("");
    const revision = stateRevision.current;
    try { const result = browserState(await launcherBrowserBridge().invoke(operation)); if (revision === stateRevision.current) { currentState.current = result; setState(result); } return result; }
    catch { setError(copy.operationFailed); return null; }
  }, [copy]);
  useEffect(() => {
    let live = true;
    try {
      const bridge = launcherBrowserBridge();
      const unsubscribe = bridge.onChanged(value => { if (!live) return; try { const next = browserState(value); stateRevision.current += 1; if (next.takeover && !currentState.current.takeover) continuation.current?.cancel(); currentState.current = next; setState(next); } catch { setError(copy.stateUnavailable); } });
      const revision = stateRevision.current;
      void bridge.invoke({ operation: "state" }).then(value => { if (live && revision === stateRevision.current) { const next = browserState(value); currentState.current = next; setState(next); } }).catch(() => { if (live) setError(copy.stateUnavailable); });
      return () => { live = false; unsubscribe(); };
    } catch { setError(copy.browserUnavailable); }
  }, [copy]);
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
      const overlay = document.querySelector('[data-vui="dialog-overlay"], [data-vui="popover"], [role="alertdialog"], [role="menu"], [role="listbox"]');
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
    try { url = safeBrowserUrl(value); } catch { setError(copy.invalidAddress); return; }
    const result = await run(draft || !active ? { operation: "open", url } : { operation: "navigate", pageId: active.id, url });
    if (result) { setDraft(false); setMobilePage("web"); }
  }
  async function changeOwner() {
    if (ownerPending.current) return;
    ownerPending.current = true; setPending(true);
    const resume = state.takeover;
    const control = continuation.current;
    if (!resume) control?.cancel();
    const intent = resume ? control?.capture() : null;
    try {
      const result = await run({ operation: resume ? "resume" : "takeover" });
      if (resume && result && !result.takeover && !currentState.current.takeover) control?.complete(intent || null, () => !currentState.current.takeover);
    } finally { ownerPending.current = false; setPending(false); }
  }
  const browser = <section className={styles.browser} aria-label={copy.browser}>
    <header className={styles.header}>
      <span className={styles.heading}><Globe size={16} />{copy.web}</span>
      <div className={styles.controls}><span className={styles.ownership}>{state.takeover ? copy.ownedByUser : copy.ownedByAssistant}</span>
        <VButton isPending={pending} onClick={() => void changeOwner()}>{state.takeover ? copy.handOff : pending ? copy.waiting : copy.takeOver}</VButton>
        <VButton variant="ghost" isIconOnly className={styles.icon} aria-label={full ? copy.backToChat : copy.expandWeb} onClick={() => { setFull(!full); if (full && narrow) setMobilePage("chat"); }}>
          {full ? <MessageCircle size={16} /> : <Maximize2 size={16} />}</VButton>
        <VIconButton variant="ghost" className={styles.icon} label={copy.collapseWeb} title={copy.collapseWeb} icon={<PanelRightClose size={16} />} onClick={() => { setFull(false); setCollapsed(true); setMobilePage("chat"); }} /></div>
    </header>
    <div className={styles.tabs} aria-label={copy.tabs}>
      {state.pages.map(page => <div key={page.id} className={`${styles.pageTab} ${page.id === state.activePageId && !draft ? styles.pageTabActive : ""}`}>
        <VButton variant="ghost" className={styles.pageTabButton} aria-pressed={page.id === state.activePageId && !draft} onClick={() => { setDraft(false); void run({ operation: "select", pageId: page.id }); }}>{page.title || page.url || copy.webPage}</VButton>
        <VButton variant="ghost" isIconOnly className={styles.icon} aria-label={`${copy.closeTab} ${page.title || copy.webPage}`} onClick={() => void run({ operation: "close", pageId: page.id })}><X size={13} /></VButton>
      </div>)}
      <VButton variant="ghost" isIconOnly className={styles.icon} aria-label={copy.newPage} isDisabled={state.pages.length >= 4} onClick={() => { setDraft(true); setAddress(""); setError(""); }}><Plus size={16} /></VButton>
    </div>
    <form className={styles.addressBar} onSubmit={event => { event.preventDefault(); void go(); }}>
      <VButton type="button" variant="ghost" isIconOnly className={styles.icon} aria-label={copy.back} isDisabled={!active || draft || !active.canGoBack} onClick={() => active && void run({ operation: "back", pageId: active.id })}><ArrowLeft size={16} /></VButton>
      <VButton type="button" variant="ghost" isIconOnly className={styles.icon} aria-label={copy.forward} isDisabled={!active || draft || !active.canGoForward} onClick={() => active && void run({ operation: "forward", pageId: active.id })}><ArrowRight size={16} /></VButton>
      <VButton type="button" variant="ghost" isIconOnly className={styles.icon} aria-label={copy.reload} isDisabled={!active || draft} onClick={() => active && void run({ operation: "reload", pageId: active.id })}><RotateCw size={16} /></VButton>
      <VInput className={styles.addressInput} aria-label={copy.address} value={address} placeholder={copy.addressPlaceholder} onChange={event => setAddress(event.target.value)} />
      <VButton type="submit">{copy.open}</VButton>
    </form>
    {error || active?.loadError ? <p role="alert" className={styles.error}>{error || copy.loadFailed}</p> : null}
    {active?.loading && !draft ? <div role="progressbar" aria-label={copy.loading} className={styles.progress} /> : null}
    <div className={styles.viewportContainer}>
      {(!active || draft) ? <div className={styles.empty}><Globe size={28} /><p>{copy.emptyHint}</p><VButton onClick={() => void go("https://www.bilibili.com/")}>{copy.bilibili}</VButton></div> : null}
      <div ref={viewRef} data-launcher-browser-viewport="true" className={canShowPage ? styles.viewport : styles.viewportHidden} />
    </div>
  </section>;
  return <div ref={workspaceRef} className={styles.root} data-vui-domain-recipe="launcher-assistant-browser">
    {narrow && !collapsed ? <div className={styles.mobileSwitch}><VButton variant={!webVisible ? "secondary" : "ghost"} aria-pressed={!webVisible} onClick={() => { setFull(false); setMobilePage("chat"); }}>{copy.chat}</VButton><VButton variant={webVisible ? "secondary" : "ghost"} aria-pressed={webVisible} onClick={() => { setCollapsed(false); setMobilePage("web"); }}>{copy.web}</VButton></div> : null}
    {collapsed ? <VButton variant="ghost" className={styles.restore} aria-label={copy.openPage} icon={<Globe size={16} />} onClick={() => { setCollapsed(false); setMobilePage("web"); }}>{copy.web}</VButton> : null}
    <VSplitWorkspace className={`${styles.split} ${!webVisible ? styles.chatOnly : narrow || full ? styles.webOnly : ""}`} resize={{ layoutId: WORKBENCH_LAYOUT_IDS.launcherAssistantBrowser, sidebar: { defaultWidth: 360, minWidth: chatMinWidth, maxWidth: Math.max(chatMinWidth, Math.floor(workspaceWidth - browserMinWidth - PANE_RESIZE_HANDLE_WIDTH)) } }}
      sidebar={<LauncherAssistantRoute embedded navigationOwned {...assistantProps} onControlContinuationReady={bindContinuation} />}
      main={browser} />
  </div>;
}
