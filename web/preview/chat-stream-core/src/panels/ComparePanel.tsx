import { useMemo } from "react";

import { buildSyntheticConversation } from "../mock/syntheticConversation";
import { CurrentTimeline } from "../current/CurrentTimeline";
import { VirtualTimeline } from "../next/VirtualTimeline";

/** Tab ①: same synthetic 500+ message session rendered by both strategies. */
export function ComparePanel() {
  const messages = useMemo(() => buildSyntheticConversation(520), []);
  return (
    <div style={{ display: "flex", flexDirection: "column", flex: 1, minHeight: 0 }}>
      <p className="panel-note">
        同一份<b>确定性合成会话</b>（520 条：中文文案 / 代码块 / 表格 / 长工具输出，seed 固定）。
        左栏复刻现状：客户端消息窗口（首屏 12、上滚 +12、软上限 72）+ 自研 spacer 虚拟化
        （真实 <b>resolveConversationVirtualRange</b> + 行高缓存 + 行键锚定）。右栏新方案：整段历史
        react-virtual 虚拟化（动态测高 + 行高缓存 + 前插自动锚定），运行中 turn 独立渲染成 live-tail。
      </p>
      <div className="compare-grid" style={{ flex: 1, minHeight: 0 }}>
        <div className="compare-col">
          <div className="compare-col-head">
            <h2>A · 现状复刻</h2>
            <span className="tag">窗口 12/+12/72 + spacer 虚拟化</span>
          </div>
          <CurrentTimeline messages={messages} />
        </div>
        <div className="compare-col">
          <div className="compare-col-head">
            <h2>B · 新方案</h2>
            <span className="tag next">react-virtual + live-tail</span>
          </div>
          <VirtualTimeline messages={messages} />
        </div>
      </div>
    </div>
  );
}
