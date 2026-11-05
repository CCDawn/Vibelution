/** Exact Agent configuration metadata; native argumentsHash owns execution binding. */
type Summary = Record<string, unknown> | null | undefined;
type Rule = (value: unknown) => boolean;
const ACTIONS = new Set(["agent_parameters_update", "agent_prompt_update"]);
const record = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value);
const text = (value: unknown, max = 16000, empty = false) => typeof value === "string"
  && (empty || value.length > 0) && Array.from(value).length <= max && !/[\p{Cc}\p{Cf}\p{Cs}\p{Zl}\p{Zp}]/u.test(value);
const id = (value: unknown) => typeof value === "string" && /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}(?![\s\S])/.test(value);
const requestId = (value: unknown) => typeof value === "string" && /^[A-Za-z0-9][A-Za-z0-9_-]{0,95}(?![\s\S])/.test(value);
const digest = (value: unknown) => typeof value === "string" && /^[a-f0-9]{64}(?![\s\S])/.test(value);
const contentHash = (value: unknown) => typeof value === "string" && /^sha256:[a-f0-9]{64}(?![\s\S])/.test(value);
const boolean: Rule = value => typeof value === "boolean";
const oneOf = (...values: unknown[]): Rule => value => values.includes(value);
const exact = (value: unknown, rules: Record<string, Rule>) => record(value)
  && Object.keys(value).length === Object.keys(rules).length
  && Object.entries(rules).every(([key, rule]) => Object.hasOwn(value, key) && rule(value[key]));
const decimal = (min: number, max?: number): Rule => value => typeof value === "string"
  && /^(0|[1-9][0-9]*)(?![\s\S])/.test(value) && value.length <= 16000
  && BigInt(value) >= BigInt(min) && (max === undefined || BigInt(value) <= BigInt(max));
const fraction: Rule = value => typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= 1;
const canonicalText = (max: number, empty = false): Rule => value => text(value, max, empty) && value === (value as string).trim();
const compressionLevels = (rule: Rule): Rule => value => exact(value, { light: rule, standard: rule, deep: rule, emergency: rule });
const compressionPolicy: Rule = value => exact(value, {
  mode: oneOf("custom"), enabled: boolean, maxTokenLimit: decimal(1, 2000000), maxCompressionsPerSession: decimal(1, 100),
  levels: compressionLevels(fraction), summaryChars: compressionLevels(decimal(1, 20000)),
  preservation: item => exact(item, { keepAiMessages: decimal(1, 50), preserveErrors: boolean, extractKeyDecisions: boolean,
    retentionFocus: focus => focus === null || Array.isArray(focus) && focus.every(entry => text(entry, 16000, true)) }),
  policyVersion: decimal(0, 1000000), compressionTriggerTokenLimit: decimal(0, 2000000), postCompressionTargetTokenLimit: decimal(0, 2000000),
});

export function agentConfigurationApprovalActionIsKnown(value: unknown): boolean {
  return typeof value === "string" && ACTIONS.has(value);
}

/** Only complete typed metadata may enable manual approval for these two writes. */
export function agentConfigurationApprovalPreviewIsValid(summary: Summary): boolean {
  if (!summary || !agentConfigurationApprovalActionIsKnown(summary.assistantAction) || summary.assistantPlatformPreviewVersion !== 1
    || summary.assistantArgumentsInvalid || summary.assistantDetailsOmitted !== false || !digest(summary.assistantParametersDigest)) return false;
  const allowed = new Set(["argumentKeys", "assistantPlatformPreviewVersion", "assistantAction", "assistantTargets", "assistantParametersDigest",
    "assistantChangedFields", "assistantDelta", "assistantContentOmitted", "assistantDetailsOmitted"]);
  try {
    if (Object.keys(summary).some(key => !allowed.has(key)) || Array.from(JSON.stringify(summary)).length > 16000) return false;
  } catch { return false; }
  if (Object.hasOwn(summary, "argumentKeys") && (!Array.isArray(summary.argumentKeys) || summary.argumentKeys.length !== 2
    || new Set(summary.argumentKeys).size !== 2 || !summary.argumentKeys.every(key => key === "action" || key === "arguments_json"))) return false;
  const targets = summary.assistantTargets;
  const delta = summary.assistantDelta;
  const fields = summary.assistantChangedFields;
  if (!record(targets) || !record(delta) || !Array.isArray(fields)) return false;
  const sameFields = (...expected: string[]) => fields.length === expected.length && expected.every((value, index) => fields[index] === value);
  const targetRules: Record<string, Rule> = { project_id: id, request_id: requestId, agent_id: id, expected_config_revision: decimal(0) };
  if (summary.assistantAction === "agent_prompt_update") {
    Object.assign(targetRules, { expected_template_id: id, expected_content_hash: contentHash });
    return exact(targets, targetRules) && sameFields("promptContent", "promptTemplateId") && summary.assistantContentOmitted === true
      && exact(delta, { scope: oneOf("single_agent_copy_on_write"), activation: oneOf("next_submission"), contentChars: decimal(1, 8000), contentDigest: digest });
  }
  targetRules.kind = oneOf("model", "budget", "compression");
  if (!exact(targets, targetRules) || !sameFields(targets.kind as string) || summary.assistantContentOmitted !== false) return false;
  if (targets.kind === "model") return exact(delta, { expected_model_ref: canonicalText(200), context_window: decimal(1), reasoning_effort: canonicalText(80, true) });
  if (targets.kind === "budget") return exact(delta, { maxCallsPerTurn: value => value === null || decimal(0, 200)(value) });
  return exact(delta, { policy: compressionPolicy });
}

export function agentConfigurationApprovalText(summary: Summary, lang: "zh" | "en"): string {
  const prompt = summary?.assistantAction === "agent_prompt_update";
  const title = prompt ? (lang === "zh" ? "修改 Agent 角色正文" : "Update Agent role prompt")
    : (lang === "zh" ? "修改 Agent 参数" : "Update Agent parameters");
  if (!agentConfigurationApprovalPreviewIsValid(summary)) return `${title}\n${lang === "zh"
    ? "参数无法核对，请拒绝并重新发起。" : "Arguments cannot be verified. Decline and request again."}`;
  const targets = summary!.assistantTargets as Record<string, string>;
  const delta = summary!.assistantDelta as Record<string, unknown>;
  const lines = [title, `${lang === "zh" ? "项目" : "Project"}: ${targets.project_id}`, `Agent: ${targets.agent_id}`,
    `${lang === "zh" ? "请求 ID" : "Request ID"}: ${targets.request_id}`,
    `${lang === "zh" ? "原配置版本" : "Previous configuration revision"}: ${targets.expected_config_revision}`];
  if (prompt) return [...lines, `${lang === "zh" ? "原角色模板" : "Previous role template"}: ${targets.expected_template_id}`,
    `${lang === "zh" ? "原内容指纹" : "Previous content fingerprint"}: ${targets.expected_content_hash}`,
    `${lang === "zh" ? "正文字符数" : "Prompt characters"}: ${delta.contentChars}`,
    `${lang === "zh" ? "新内容指纹" : "New content fingerprint"}: ${delta.contentDigest}`,
    lang === "zh" ? "正文已隔离；仅为此 Agent 复制写入角色模板，从下一次新提交开始生效，不修改共享模板。"
      : "Prompt body is isolated. Copy on write for this Agent only; activates on the next new submission and preserves the shared template."].join("\n");
  const kindLabels: Record<string, string> = { model: "模型", budget: "预算", compression: "压缩" };
  lines.push(`${lang === "zh" ? "参数类别" : "Parameter type"}: ${lang === "zh" ? `${kindLabels[targets.kind]}（${targets.kind}）` : targets.kind}`,
    JSON.stringify(delta, null, 2));
  if (targets.kind === "budget") lines.push(delta.maxCallsPerTurn === null ? (lang === "zh" ? "清除 Agent 调用次数覆盖值，恢复默认。" : "Clear the Agent call-limit override and restore the default.")
    : delta.maxCallsPerTurn === "0" ? (lang === "zh" ? "调用次数设为 0：不限制。" : "Set the call limit to 0: unlimited.")
      : (lang === "zh" ? "设置每回合调用次数上限。" : "Set the per-turn call limit."));
  return lines.join("\n");
}
