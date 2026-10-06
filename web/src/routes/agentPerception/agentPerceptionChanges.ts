import { canonicalAgentPerceptionPolicy } from "./agentPerceptionDraft";
import type { AgentPerceptionPolicy, AgentPerceptionSourceId } from "./types";

/** Display-only comparison. The existing draft and server revision still own saving. */
export function perceptionPolicyChanges(draft: AgentPerceptionPolicy, saved: AgentPerceptionPolicy, lang: "zh" | "en"): string[] {
  const next = canonicalAgentPerceptionPolicy(draft);
  const previous = canonicalAgentPerceptionPolicy(saved);
  const text = (zh: string, en: string) => lang === "zh" ? zh : en;
  const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);
  const sources: Record<AgentPerceptionSourceId, string> = {
    personal: text("个人记忆与私有知识库", "Personal memory and private knowledge base"),
    team: text("指定团队", "Selected teams"), knowledge: text("授权知识库", "Authorized knowledge bases"),
    projects: text("本地成熟项目索引", "Local mature-project index"),
  };
  const modes = { off: text("关闭", "Off"), manual: text("按需查询", "On demand"), auto: text("自动感知", "Automatic") };
  const changes: string[] = [];
  if (next.enabled !== previous.enabled) changes.push(text(`感知控制：${previous.enabled ? "开启" : "关闭"} → ${next.enabled ? "开启" : "关闭"}`, `Perception: ${previous.enabled ? "on" : "off"} → ${next.enabled ? "on" : "off"}`));
  (Object.keys(sources) as AgentPerceptionSourceId[]).forEach(source => {
    if (next.sources[source].mode !== previous.sources[source].mode) changes.push(`${sources[source]}：${modes[previous.sources[source].mode]} → ${modes[next.sources[source].mode]}`);
    if (!same(next.sources[source].triggers, previous.sources[source].triggers)) changes.push(text(`${sources[source]}：自动触发条件已调整`, `${sources[source]}: automatic triggers changed`));
  });
  if (!same(next.sources.team.teamIds, previous.sources.team.teamIds)) changes.push(text("指定团队：读取范围已调整", "Selected teams: read scope changed"));
  if (!same(next.sources.knowledge, previous.sources.knowledge) && (
    next.sources.knowledge.scope !== previous.sources.knowledge.scope
    || !same(next.sources.knowledge.knowledgeBaseIds, previous.sources.knowledge.knowledgeBaseIds)
    || !same(next.sources.knowledge.excludedKnowledgeBaseIds, previous.sources.knowledge.excludedKnowledgeBaseIds)
  )) changes.push(text("授权知识库：读取范围或排除项已调整", "Authorized knowledge bases: scope or exclusions changed"));
  if (next.background.enabled !== previous.background.enabled) changes.push(text(`后台调研：${next.background.enabled ? "开启" : "关闭"}`, `Background research: ${next.background.enabled ? "on" : "off"}`));
  if (!same(next.background.topics, previous.background.topics)) changes.push(text(`调研主题：${previous.background.topics.length} → ${next.background.topics.length} 个（内容已调整）`, `Research topics: ${previous.background.topics.length} → ${next.background.topics.length} (content changed)`));
  const budgets = ["intervalMinutes", "dailyMaxRuns", "maxCallsPerRun", "maxInputTokensPerRun", "maxResultChars", "maxConcurrent"] as const;
  if (budgets.some(key => next.background[key] !== previous.background[key])) changes.push(text("调研频率或用量限制已调整", "Research schedule or usage limits changed"));
  if (next.notifications.mode !== previous.notifications.mode) changes.push(text("更新通知方式已调整", "Update notification mode changed"));
  return changes;
}
