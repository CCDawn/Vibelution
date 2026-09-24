/**
 * 预览演示数据 —— 只含 UI 文案与确定性初始态，不含任何键位知识
 * （键位知识只允许收敛在 web/src/shortcuts 的 commands.ts）。
 */
import type { ShortcutCommandId } from "../../../src/shortcuts/commands";

/** 命令说明文案（模拟项：真实命令表暂无 description 字段，集成时需裁决归属）。 */
export const COMMAND_DESCRIPTIONS: Readonly<Record<ShortcutCommandId, string>> = {
  openCommandPalette: "在应用任意位置唤起命令面板，快速跳转页面与执行动作",
  openSessionSearch: "在应用任意位置唤起会话搜索，跨会话检索历史对话",
};

export type PreviewBootState = "default" | "recording" | "conflict" | "reserved" | "cleared";

/** URL ?state= 确定性初始态（截图与人工复现用；录制/冲突也可用真实交互触发）。 */
export function readPreviewBootState(): PreviewBootState {
  const raw = new URLSearchParams(window.location.search).get("state");
  return raw === "recording" || raw === "conflict" || raw === "reserved" || raw === "cleared"
    ? raw
    : "default";
}

/** 占用冲突演示：把命令面板正占用的 CmdOrCtrl+k 绑到会话搜索 → 占用拒绝。 */
export const CONFLICT_DEMO: { commandId: ShortcutCommandId; binding: string } = {
  commandId: "openSessionSearch",
  binding: "CmdOrCtrl+k",
};

/** 保留键演示：Enter 是对话框确认键，绑定全局即被拒绝。 */
export const RESERVED_DEMO: { commandId: ShortcutCommandId; binding: string } = {
  commandId: "openSessionSearch",
  binding: "Enter",
};
