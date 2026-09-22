import { createRoot } from "react-dom/client";

import "./base.css";
import "./tokens.css";
import "./tailwind.css";
import "./quiet-workbench-preview.css";

type Mode = "current" | "proposed";

const NAV = ["对话", "代理", "团队", "科研"] as const;

function Bench({ mode }: { mode: Mode }) {
  const proposed = mode === "proposed";
  return (
    <div className={`bench is-${mode}`} data-preview-mode={mode}>
      <div className="chrome">
        <header className="topbar">
          <nav aria-label="主导航">
            {NAV.map((item) => (
              <span key={item} className={item === "对话" ? "nav is-active" : "nav"}>
                {item}
              </span>
            ))}
          </nav>
          <span className="status">后端正常</span>
        </header>
        <div className="body">
          <aside className="rail" aria-label="会话">
            <p className="rail-label">会话</p>
            <div className="session is-active">
              <strong>终态重复</strong>
              <span>刚刚</span>
            </div>
            <div className="session">
              <strong>科研档案</strong>
              <span>昨天</span>
            </div>
          </aside>
          <section className="thread" aria-label="对话">
            <article className="turn is-user">
              <p>第二次终态还会写进账本吗？</p>
            </article>
            <article className="turn is-assistant">
              <p className="thought">先核对真实账本，再决定拦哪一种。</p>
              <div className="answer">
                <p>同一回合已经收口之后，再来的终态会被拒绝。其它还没在真实账本里出现过的写法，仍然只记录、不拦截。</p>
              </div>
            </article>
            <form className="composer" onSubmit={(event) => event.preventDefault()}>
              <label className="sr-only" htmlFor={`draft-${mode}`}>
                继续输入
              </label>
              <textarea id={`draft-${mode}`} rows={2} readOnly value="继续问一个具体回合" />
              <button type="submit">发送</button>
            </form>
          </section>
        </div>
      </div>
    </div>
  );
}

function App() {
  return (
    <main className="page">
      <header className="intro">
        <p className="eyebrow">隔离预览 · 模拟数据</p>
        <h1>把工作台收安静</h1>
        <p>左边是现在的深色工作台：背景有光晕和星点，回复、思考和选中项各自带框。右边只改这三处，信息不变。</p>
      </header>
      <div className="compare">
        <section>
          <h2>现在</h2>
          <Bench mode="current" />
        </section>
        <section>
          <h2>建议</h2>
          <Bench mode="proposed" />
        </section>
      </div>
      <p className="footnote">没有连接真实会话，也没有改正式界面。窄屏时两栏上下排列。</p>
    </main>
  );
}

const root = document.getElementById("root");
if (!root) {
  throw new Error("quiet workbench preview root is missing");
}
createRoot(root).render(<App />);
