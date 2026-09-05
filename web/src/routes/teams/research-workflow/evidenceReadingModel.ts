/** Reading labels never upgrade candidate relationships into verified findings. */
export const relationLabelsZh: Record<string, string> = {
  supports: "支持", derives: "推导", survey_complement: "综述互补",
  references_official_definition: "引用官方定义", problem_motivates_progress: "推动相关进展",
  survey_contextualizes_breakthrough: "为突破提供综述背景", duplicate_different_locator: "同一文献的不同入口",
  partial_result_cited_in_survey: "部分结果被综述引用", ml_negative_contrasts_survey: "机器学习负面结果与综述对照",
  unreviewed_proof_vs_official_criteria: "未评审证明与官方标准对照", analytical_approaches_parallel: "解析方法并列",
  media_reports_same_breakthrough: "报道同一突破", source_supports_theme: "提供主题依据",
  defines_problem_scope: "界定问题范围", motivates_verification: "推动验证", covers_methods: "涵盖相关方法",
  contextualizes_progress: "提供进展背景", complements_partial_results: "补充部分结果",
  contrasts_methodology: "方法对照", claims_resolution: "声称解决", corroborates: "相互印证",
  grounds_on: "以其为依据", reports_on: "报道", extends: "拓展", duplicate_of: "重复文献",
  assumes_rh: "以黎曼猜想为前提", contrasts_with: "与之对照", claims_to_resolve: "声称解决",
  tests_limits_of: "检验其局限", contextualizes: "提供背景", conditionally_supports: "有条件支持",
  empirically_tested_by: "由其进行经验检验", analytically_approximates: "解析近似",
  shares_statistics_with: "具有共同统计特征", methodologically_contrasts_with: "方法论对照",
  cautious_vs_premature: "审慎结论与过早断言对照", motivated_by: "受其启发",
};

export function safeSourceUrl(value: unknown): string | null {
  if (typeof value !== "string" || !/^https?:\/\//i.test(value)) return null;
  try {
    const url = new URL(value);
    return !url.username && !url.password ? url.href : null;
  } catch { return null; }
}

export function evidenceTitle(node: { id: string; [key: string]: unknown }): string {
  for (const field of ["title", "claim", "evidenceId"]) {
    if (typeof node[field] === "string" && node[field]) return node[field];
  }
  return node.id;
}
