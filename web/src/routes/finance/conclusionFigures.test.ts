import { describe, expect, it } from "vitest";
import { filingExcerptsFromToolOutput, groundResearchConclusion } from "./conclusionFigures";

const page = [{ page: 5, text: "营业收入 200.00 元 1.50 2.50 2.00 3.00 150.00 200.00 15.38" }];

describe("research conclusion figures", () => {
  it("hides an uncited ratio and keeps a cited amount outside the risk section", () => {
    const grounded = groundResearchConclusion("## 结论\n营业收入 200.00 元，见第5页。毛利率约为 91.93%。\n## 风险\n跌幅 9.99%。", [{ page: 5, text: "营业收入 200.00 元" }]);
    expect(grounded).toContain("200.00 元");
    expect(grounded).toContain("9.99%");
    expect(grounded).not.toContain("91.93");
    expect(grounded).toContain("没有这一项");
  });

  it("checks percent rounding, subtraction and a result used by the next expression", () => {
    const ratio = groundResearchConclusion("## 结论\n2.00 / 3.00 = 66.67%，2.00 / 3.00 = 0.67。见第5页。", page);
    expect(ratio).toContain("66.67%");
    expect(ratio).toContain("0.67");
    const percent = groundResearchConclusion("## 结论\n150.00 / 200.00 = 75.00%，150.00 / 200.00 = 0.75%。见第5页。", page);
    expect(percent).toContain("75.00%");
    expect(percent).not.toContain("0.75%");
    const difference = groundResearchConclusion("## 结论\n1.50 - 2.50 = -1.00。见第5页。", page);
    expect(difference).toContain("-1.00");
    const chain = groundResearchConclusion("## 结论\n1.50 + 2.50 = 4.00，4.00 * 2.00 = 8.00。见第5页。", page);
    expect(chain).toContain("8.00");
  });

  it("leaves non-conclusions, code, links and fullwidth digits as written", () => {
    expect(groundResearchConclusion("## 风险\n跌幅 9.99%。", [])).toBe("## 风险\n跌幅 9.99%。");
    expect(groundResearchConclusion("营收 12 亿元", [])).toBe("营收 没有这一项");
    const fenced = groundResearchConclusion("## 结论\n正文 12 亿元。\n```\n12 亿元\n```", []);
    expect(fenced).toContain("```\n12 亿元\n```");
    expect(fenced).not.toContain("正文 12 亿元");
    const linked = groundResearchConclusion("## 结论\n见 https://example.com/12.50 之后 12.50 元", []);
    expect(linked).toContain("https://example.com/12.50");
    expect(linked.endsWith("之后 没有这一项")).toBe(true);
    const fullwidth = groundResearchConclusion("## 结论\n营业收入 ２００.００ 元，见第5页。毛利率 ９１.９３％。", [{ page: 5, text: "200.00" }]);
    expect(fullwidth).toContain("２００.００ 元");
    expect(fullwidth).not.toContain("９１.９３");
    const glued = groundResearchConclusion("## 结论\n下跌-15.38%。见第5页。", page);
    expect(glued).not.toContain("-15.38");
    const once = groundResearchConclusion("## 结论\n毛利率 91.93%。", []);
    expect(groundResearchConclusion(once, [])).toBe(once);
  });

  it("reads a filing page only from a whole evidence-search object", () => {
    const output = JSON.stringify({
      results: [{ knowledgeItemId: "k1", excerpt: "营业收入 200.00 元" }],
      citations: [{ knowledgeItemId: "k1", financialEvidence: [{ page: "5" }] }],
    });
    expect(filingExcerptsFromToolOutput("financial_evidence_search_tool", output)).toEqual([{ page: 5, text: "营业收入 200.00 元" }]);
    expect(filingExcerptsFromToolOutput("news_search_tool", output)).toEqual([]);
    expect(filingExcerptsFromToolOutput("financial_report_query_tool", output)).toEqual([]);
    expect(filingExcerptsFromToolOutput("financial_evidence_search_tool", output.replace('"5"', "true"))).toEqual([]);
    expect(filingExcerptsFromToolOutput("financial_evidence_search_tool", "{")).toEqual([]);
  });
});
