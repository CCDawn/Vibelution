import { useState } from "react";

import { ComparePanel } from "./panels/ComparePanel";
import { StreamPanel } from "./panels/StreamPanel";
import { ProjectionPanel } from "./panels/ProjectionPanel";

type TabId = "compare" | "stream" | "projection";

const TABS: Array<{ id: TabId; label: string }> = [
  { id: "compare", label: "① A/B 长列表对比" },
  { id: "stream", label: "② 流式双模模拟" },
  { id: "projection", label: "③ 投影不变量演示" },
];

/**
 * Isolated preview shell for the chat stream core upgrade (Wave 1b).
 * Registered NOWHERE in the production router; imports real web/src logic
 * modules read-only; all data is deterministic mock data.
 */
export function App() {
  const [tab, setTab] = useState<TabId>("compare");
  return (
    <div className="preview-shell">
      <div className="preview-topbar">
        <h1>Chat Stream Core · 隔离预览（Wave 1b）</h1>
        <span className="badge">未接入生产 router</span>
        <span className="badge">web/src 零改动</span>
        <span className="badge">确定性 mock 数据</span>
        <nav className="preview-tabs">
          {TABS.map((entry) => (
            <button
              key={entry.id}
              className={tab === entry.id ? "active" : ""}
              onClick={() => setTab(entry.id)}
            >
              {entry.label}
            </button>
          ))}
        </nav>
      </div>
      <div className="preview-body">
        {tab === "compare" ? <ComparePanel /> : null}
        {tab === "stream" ? <StreamPanel /> : null}
        {tab === "projection" ? <ProjectionPanel /> : null}
      </div>
    </div>
  );
}
