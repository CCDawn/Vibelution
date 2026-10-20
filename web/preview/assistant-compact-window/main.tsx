import { useEffect, useRef, useState, type CSSProperties } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ArrowUp, Check, ChevronDown, CircleAlert, ExternalLink, MessageCircle, MoreHorizontal, Plus, ShieldCheck, Sparkles, X } from "lucide-react";
import { VButton, VDropdownMenu, VIconButton, VNativeButton, VSkeleton, VTextarea, VuiProvider } from "../../src/components/vui";
import { WhaleRigCharacter } from "../../src/routes/desktopPet/WhaleRigCharacter";
import { queryKeys } from "../../src/api/queryKeys";
import "../../src/design/tokens.css";
import "../../src/design/base.css";
import "../../src/design/tailwind.css";
import "../../src/design/vui-provider-theme.css";
import "../../src/design/route-css/desktop-pet.tailwind.css";
import "./preview.css";

// The reused character reads language from this seeded cache. No live queries.
const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false, refetchOnWindowFocus: false, refetchOnReconnect: false } } });
client.setQueryData(queryKeys.configPublic(), { language: "zh" });

type Scene = "chat" | "empty" | "loading" | "error";
type Message = { role: "user" | "assistant"; text: string };
const sceneLabels: Record<Scene, string> = { chat: "聊天", empty: "空会话", loading: "加载中", error: "连接错误" };
const initialMessages: Message[] = [
  { role: "user", text: "今天事情有点多，帮我理一理。" },
  { role: "assistant", text: "可以，先从最重要的事开始。" },
];

function App() {
  const [small, setSmall] = useState(false);
  const [scene, setScene] = useState<Scene>("chat");
  const [chatOpen, setChatOpen] = useState(true);
  const [draft, setDraft] = useState("");
  const [messages, setMessages] = useState(initialMessages);
  const [model, setModel] = useState("默认模型");
  const [permission, setPermission] = useState("按需审批");
  const [notice, setNotice] = useState("");
  const end = useRef<HTMLDivElement>(null);
  const canSend = scene !== "loading" && scene !== "error" && Boolean(draft.trim());

  useEffect(() => { end.current?.scrollIntoView({ block: "nearest" }); }, [messages]);

  function send() {
    if (!canSend) return;
    const text = draft.trim();
    setMessages(current => [...(scene === "empty" ? [] : current), { role: "user", text },
      { role: "assistant", text: "收到。我们先选一件今天必须完成的事，再把其他事情放到合适的时间。" }]);
    setDraft("");
    setScene("chat");
    setNotice("已添加本地模拟消息。");
  }

  function chooseScene(next: Scene) {
    setScene(next);
    setMessages(initialMessages);
    setNotice("");
    setChatOpen(true);
  }

  const dimensions = { "--window-width": small ? "340px" : "400px", "--window-height": small ? "500px" : "530px" } as CSSProperties;

  return <VuiProvider><main className="compact-preview">
    <header className="preview-heading">
      <div><p className="preview-kicker">个人助理 / 桌面聊天</p><h1>小窗里，也能好好聊。</h1>
        <p className="preview-description">把空间留给对话。关闭聊天，助理仍在桌面。</p></div>
      <div className="preview-controls" aria-label="预览设置">
        <div className="size-controls" aria-label="窗口尺寸">
          <VButton variant={!small ? "secondary" : "ghost"} aria-pressed={!small} onClick={() => setSmall(false)}>400 × 530</VButton>
          <VButton variant={small ? "secondary" : "ghost"} aria-pressed={small} onClick={() => setSmall(true)}>340 × 500</VButton>
        </div>
        <VDropdownMenu aria-label="模拟界面状态" align="end"
          trigger={<VButton variant="secondary" icon={<ChevronDown size={13} />}>{sceneLabels[scene]}</VButton>}
          items={(Object.keys(sceneLabels) as Scene[]).map(id => ({ id, label: sceneLabels[id], onSelect: () => chooseScene(id) }))} />
      </div>
    </header>

    <div className="preview-layout">
      <section className="desktop-canvas" aria-label="浮动助理窗口预览" style={dimensions} data-preview-size={small ? "340x500" : "400x530"}>
        <span className="canvas-label">{chatOpen ? `${small ? "340 × 500" : "400 × 530"} · 实际尺寸` : "聊天已收起 · 助理仍在"}</span>
        {chatOpen ? <section className="assistant-window" aria-label="个人助理聊天小窗" data-vui-domain-recipe="desktop-assistant" data-expanded="true">
          <header className="assistant-header">
            <span className="assistant-avatar" aria-hidden="true"><Sparkles size={17} /></span>
            <div className="assistant-identity"><strong>个人助理</strong><span><i />{scene === "loading" ? "正在读取会话" : scene === "error" ? "连接暂不可用" : "大肥鲸 · 随时聊聊"}</span></div>
            <div className="assistant-header-actions">
              <VIconButton variant="ghost" label="返回工作台" icon={<ExternalLink size={15} />} onClick={() => setNotice("预览：这里将返回工作台，继续同一个助理会话。")} />
              <VIconButton variant="ghost" label="关闭聊天，保留桌面助理" icon={<X size={17} />} onClick={() => { setChatOpen(false); setNotice(""); }} />
            </div>
          </header>

          <div className="message-scroll" aria-label="聊天消息" aria-busy={scene === "loading"}>
            {scene === "empty" ? <div className="empty-conversation"><span className="empty-mark"><MessageCircle size={23} /></span><h2>我在，想聊点什么？</h2><p>理一理思路，或交给我一件小事。</p>
              <VButton variant="secondary" onClick={() => setDraft("帮我整理一下今天的安排。")}>整理今天的安排</VButton></div>
            : scene === "loading" ? <div className="loading-conversation" role="status"><span>正在读取对话…</span><VSkeleton className="skeleton-short" /><VSkeleton /><VSkeleton className="skeleton-medium" /><VSkeleton /></div>
            : <><div className="conversation-date">今天 · 10:24</div>
              {messages.map((message, index) => <article key={index} className={`message message-${message.role}`} aria-label={message.role === "user" ? "你的消息" : "个人助理回复"}>
                {message.role === "assistant" ? <span className="message-author"><Sparkles size={12} />个人助理</span> : null}
                <p>{message.text}</p>
                {index === 1 ? <><ol className="answer-list"><li><span>1</span><div>先定一件必须完成的事</div></li><li><span>2</span><div>把零散的事放到一起处理</div></li><li><span>3</span><div>留一点空档，别把一天排满</div></li></ol><p className="answer-followup">今天有哪些事在等着你？</p></> : null}
              </article>)}
              {scene === "error" ? <div className="connection-error" role="alert"><CircleAlert size={15} /><div><strong>暂时没连上</strong><p>已有对话仍在，可以稍后重试。</p></div><VButton variant="ghost" onClick={() => chooseScene("chat")}>重试</VButton></div> : null}
              <div ref={end} />
            </>}
          </div>

          <footer className="composer-region">
            <form className="compact-composer" onSubmit={event => { event.preventDefault(); send(); }}>
              <VTextarea rows={2} minRows={2} aria-label="给个人助理发消息" placeholder="说点什么，或交给我一件事…" value={draft}
                isDisabled={scene === "loading" || scene === "error"} onChange={event => setDraft(event.target.value)}
                onKeyDown={event => { if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); send(); } }} />
              <div className="composer-toolbar" aria-label="消息工具栏">
                <VDropdownMenu aria-label="更多聊天工具" side="top" align="start"
                  trigger={<VIconButton variant="ghost" label="更多聊天工具" icon={<Plus size={16} />} />}
                  items={[{ id: "attach", label: "添加附件", onSelect: () => setNotice("附件入口示意，预览不上传文件。") },
                    { id: "context", label: "引用会话", onSelect: () => setNotice("引用入口示意，预览不读取真实会话。") },
                    { id: "settings", label: "助理设置", onSelect: () => setNotice("助理设置入口示意。") }]} />
                <VDropdownMenu aria-label="选择对话模型" side="top" align="start"
                  trigger={<VButton className="model-control" variant="ghost" contentLayout="plain"><span>{model}</span><ChevronDown size={11} /></VButton>}
                  items={["默认模型", "轻量模型", "推理模型"].map(label => ({ id: label, label, onSelect: () => setModel(label) }))} />
                <VDropdownMenu aria-label="工具权限" side="top" align="end"
                  trigger={<VButton className="permission-control" variant="ghost" contentLayout="plain"><ShieldCheck size={12} /><span>{permission}</span><ChevronDown size={11} /></VButton>}
                  items={["按需审批", "仅查看"].map(label => ({ id: label, label, onSelect: () => setPermission(label) }))} />
                <VIconButton className="send-control" type="submit" variant="primary" label="发送消息（本地模拟）" icon={<ArrowUp size={16} />} isDisabled={!canSend} />
              </div>
            </form>
            <span className="composer-hint">Enter 发送 <span>·</span> Shift + Enter 换行</span>
          </footer>
        </section> : <div className="collapsed-assistant" data-expanded="false">
          <VNativeButton className="whale-button" aria-label="点击大肥鲸打开聊天" onClick={() => setChatOpen(true)}>
            <WhaleRigCharacter animationState="idle" tone="idle" name="大肥鲸" />
          </VNativeButton>
          <VButton variant="secondary" icon={<MessageCircle size={14} />} onClick={() => setChatOpen(true)}>聊一聊</VButton>
        </div>}
      </section>

      <aside className="preview-notes"><span className="notes-kicker">这一版的重点</span><h2>轻一点，留多一点对话空间。</h2>
        <ul><li><Check size={15} /><div><strong>消息从左侧开始</strong><p>回复取消多余头像缩进，正文和步骤保持同一条阅读线。</p></div></li>
          <li><Check size={15} /><div><strong>输入区更紧凑</strong><p>输入、工具和发送集中在底部，消息区域独立滚动。</p></div></li>
          <li><Check size={15} /><div><strong>重要选项不用猜</strong><p>模型与审批文字完整显示，附件和次要入口收进加号。</p></div></li>
          <li><Check size={15} /><div><strong>关掉聊天，助理还在</strong><p>点击右上角 × 回到鲸鱼形象，点「聊一聊」恢复。</p></div></li></ul>
        <p className="preview-boundary"><MoreHorizontal size={16} />隔离预览 · 本地模拟消息、状态和选项，未连接真实会话、模型或权限操作。</p>
      </aside>
    </div>
    <div className="preview-feedback" role="status" aria-live="polite">{notice || "可切换尺寸与状态，或试试关闭聊天。"}</div>
  </main></VuiProvider>;
}

createRoot(document.getElementById("root")!).render(<QueryClientProvider client={client}><App /></QueryClientProvider>);
