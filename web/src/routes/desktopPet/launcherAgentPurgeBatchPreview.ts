const PURGE_EFFECTS = ["agent", "sessions", "private_workspace", "team_room_mode_references"] as const;
const SUMMARY_KEYS = ["assistantAction", "assistantTargets", "assistantPurgeItems", "assistantPurgeIrreversible", "assistantPurgeEffects"];

type PurgeItem = { agent_id: string; expected_config_revision: string };
type PurgeBatchSummary = {
  assistantTargets: { project_id: string; request_id: string; batchCount: string };
  assistantPurgeItems: PurgeItem[];
};

const isRecord = (value: unknown): value is Record<string, unknown> => value !== null
  && typeof value === "object" && !Array.isArray(value);
const exactKeys = (value: unknown, keys: string[]): value is Record<string, unknown> => isRecord(value)
  && Reflect.ownKeys(value).length === keys.length && keys.every(key => Object.hasOwn(value, key));
const safeId = (value: unknown, max: number): value is string => typeof value === "string"
  && value.length <= max && /^[A-Za-z0-9][A-Za-z0-9_.:-]*(?![\s\S])/.test(value);
const decimal = (value: unknown): value is string => typeof value === "string"
  && /^(0|[1-9][0-9]*)(?![\s\S])/.test(value);

/** Launcher-only: every bound target must be visible before a batch can be approved. */
export function agentPurgeBatchPreviewIsValid(summary: unknown): boolean {
  if (!isRecord(summary)) return false;
  const keys = Object.hasOwn(summary, "argumentKeys") ? [...SUMMARY_KEYS, "argumentKeys"] : SUMMARY_KEYS;
  if (!exactKeys(summary, keys) || summary.assistantAction !== "agent_purge_batch"
    || summary.assistantPurgeIrreversible !== true) return false;
  // Native tool approvals add these two keys; direct Launcher summaries do not.
  if (Object.hasOwn(summary, "argumentKeys") && (!Array.isArray(summary.argumentKeys)
    || summary.argumentKeys.length !== 2 || summary.argumentKeys[0] !== "action"
    || summary.argumentKeys[1] !== "arguments_json")) return false;
  const targets = summary.assistantTargets;
  if (!exactKeys(targets, ["project_id", "request_id", "batchCount"])
    || !safeId(targets.project_id, 160) || typeof targets.request_id !== "string"
    || !/^[A-Za-z0-9][A-Za-z0-9_-]{0,95}(?![\s\S])/.test(targets.request_id)
    || !decimal(targets.batchCount)) return false;
  const items = summary.assistantPurgeItems;
  if (!Array.isArray(items) || items.length < 1 || items.length > 50
    || targets.batchCount !== String(items.length)) return false;
  const ids = new Set<string>();
  for (const item of items) {
    if (!exactKeys(item, ["agent_id", "expected_config_revision"])
      || !safeId(item.agent_id, 128) || !decimal(item.expected_config_revision) || ids.has(item.agent_id)) return false;
    ids.add(item.agent_id);
  }
  const effects = summary.assistantPurgeEffects;
  return Array.isArray(effects) && effects.length === PURGE_EFFECTS.length
    && PURGE_EFFECTS.every((effect, index) => effects[index] === effect);
}

/** Keep the complete manifest and arbitrary-precision revisions in both languages. */
export function launcherAgentPurgeBatchActionPreview(summary: unknown, lang: "zh" | "en"): string {
  if (!agentPurgeBatchPreviewIsValid(summary)) return lang === "zh"
    ? "批量永久删除参数无法核对，不能批准。请重新获取完整的删除清单。"
    : "Batch permanent deletion parameters cannot be verified. Cannot approve; request the complete deletion manifest again.";
  const { assistantTargets: targets, assistantPurgeItems: items } = summary as PurgeBatchSummary;
  return [
    lang === "zh" ? `永久删除${targets.batchCount}个Agent` : `Permanently delete ${targets.batchCount} Agent${items.length === 1 ? "" : "s"}`,
    lang === "zh" ? `项目：${targets.project_id}` : `Project: ${targets.project_id}`,
    lang === "zh" ? `请求：${targets.request_id}` : `Request: ${targets.request_id}`,
    ...items.map((item, index) => lang === "zh"
      ? `${index + 1}. Agent：${item.agent_id}；配置版本：${item.expected_config_revision}`
      : `${index + 1}. Agent: ${item.agent_id}; config revision: ${item.expected_config_revision}`),
    lang === "zh"
      ? "不可逆范围：永久删除以上每个Agent、其全部会话、私有工作区及团队房间模式引用。此操作无法撤销。"
      : "Irreversible scope: permanently delete every listed Agent, all its sessions, private workspace, and team room mode references. This cannot be undone.",
  ].join("\n");
}
