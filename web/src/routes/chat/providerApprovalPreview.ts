/** Native argumentsHash binds execution; this projection must be complete before approval. */
type Summary = Record<string, unknown> | null | undefined;
const record = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value);
const text = (value: unknown, max: number, required = false) => typeof value === "string"
  && (!required || value.length > 0) && Array.from(value).length <= max && !/[\p{Cc}\p{Cf}\p{Cs}\p{Zl}\p{Zp}]/u.test(value);
const decimal = (value: unknown, min: number, max: number) => typeof value === "string"
  && /^(0|[1-9][0-9]*)(?![\s\S])/.test(value) && value.length <= 5 && Number(value) >= min && Number(value) <= max;

export function providerModelApprovalPreviewIsValid(summary: Summary): boolean {
  if (!summary || summary.assistantAction !== "provider_model_resolve" || summary.assistantProviderPreviewVersion !== 1
    || summary.assistantArgumentsInvalid || summary.assistantDetailsOmitted !== false
    || typeof summary.assistantParametersDigest !== "string" || !/^[a-f0-9]{64}(?![\s\S])/.test(summary.assistantParametersDigest)) return false;
  const allowed = new Set(["argumentKeys", "assistantAction", "assistantProviderPreviewVersion", "assistantArgumentsInvalid",
    "assistantDetailsOmitted", "assistantParametersDigest", "assistantTargets", "assistantOperationDescription"]);
  if (Object.keys(summary).some(key => !allowed.has(key))) return false;
  if (Object.hasOwn(summary, "assistantArgumentsInvalid") && summary.assistantArgumentsInvalid !== false
    || Object.hasOwn(summary, "assistantOperationDescription") && !text(summary.assistantOperationDescription, 300)
    || Object.hasOwn(summary, "argumentKeys") && (!Array.isArray(summary.argumentKeys) || summary.argumentKeys.length !== 2
      || new Set(summary.argumentKeys).size !== 2 || !summary.argumentKeys.every(key => key === "action" || key === "arguments_json"))) return false;
  const t = summary.assistantTargets;
  return record(t) && Object.keys(t).length === 6
    && text(t.provider_id, 64, true) && text(t.model_query, 120) && text(t.upstream_id, 200)
    && ["true", "false"].includes(t.verify as string) && decimal(t.offset, 0, 10000) && decimal(t.limit, 1, 30);
}

export function providerModelApprovalText(summary: Summary, lang: "zh" | "en"): string {
  const title = lang === "zh" ? "发现并配置连接模型" : "Discover and configure provider model";
  if (!providerModelApprovalPreviewIsValid(summary)) return `${title}\n${lang === "zh"
    ? "参数无法核对，请拒绝并重新发起。" : "Arguments cannot be verified. Decline and request again."}`;
  const t = summary!.assistantTargets as Record<string, string>;
  return [title, `${lang === "zh" ? "连接" : "Provider"}: ${t.provider_id}`,
    `${lang === "zh" ? "模型名称" : "Model name"}: ${t.model_query || (lang === "zh" ? "未指定" : "Not specified")}`,
    `${lang === "zh" ? "指定上游 ID" : "Exact upstream ID"}: ${t.upstream_id || (lang === "zh" ? "由模型目录匹配" : "Match from model catalog")}`,
    `${lang === "zh" ? "候选分页" : "Candidate page"}: offset=${t.offset}, limit=${t.limit}`,
    lang === "zh" ? "唯一匹配或指定的模型将保存到此连接；多个匹配时返回候选供选择。"
      : "A unique match or specified model will be saved to this provider; multiple matches return choices.",
    t.verify === "true" ? (lang === "zh" ? "保存后发起一次小额文本调用验证，可能产生费用。" : "After saving, run one small text verification call; charges may apply.")
      : (lang === "zh" ? "本次只配置模型，不发起文本验证。" : "Configure the model without a text verification call.")].join("\n");
}
