import type { FinancialAssistant } from "../../api/financialAssistant";

export type FinancialAssistantEntryPlan =
  | { kind: "open"; sessionId: string }
  | { kind: "create" }
  | { kind: "blocked"; message: string };

export function planFinancialAssistantEntry(
  rows: FinancialAssistant[],
  lang: "zh" | "en",
): FinancialAssistantEntryPlan {
  const ready = rows.find((row) =>
    row.status === "active" && row.setupStatus === "ready" && row.directSessionId);
  if (ready) {
    return { kind: "open", sessionId: ready.directSessionId };
  }
  if (rows.length === 0 || rows.some((row) => row.status === "active" && row.setupStatus === "pending")) {
    return { kind: "create" };
  }
  if (rows.some((row) => row.setupStatus === "profile_changed")) {
    return {
      kind: "blocked",
      message: lang === "zh"
        ? "金融助手身份配置已更改，请在 Agent 管理中核对。"
        : "The assistant identity was changed. Check it in Agent management.",
    };
  }
  return {
    kind: "blocked",
    message: lang === "zh"
      ? "金融助手已归档，请在 Agent 管理中确认是否恢复。"
      : "The assistant is archived. Restore it from Agent management if you still want it.",
  };
}

export function financialAssistantBoundary(lang: "zh" | "en"): [string, string] {
  return lang === "zh"
    ? [
        "公开新闻只作参考，助手自己判断真假，不写入财报库。分钟行情和 K 线还没接入。",
        "这里不记录账户、持仓和金额，也不会自动下单。",
      ]
    : [
        "Public news is reference only. The assistant judges whether it is credible and does not file it in the report library. Minute quotes and K-line charts are not connected.",
        "This chat does not record accounts, holdings, or amounts, and it does not place orders.",
      ];
}

export function financialConnectionFacts(row: FinancialAssistant, lang: "zh" | "en") {
  const zh = lang === "zh";
  return [
    {
      key: "model",
      label: zh ? "模型" : "Model",
      value: row.modelStatus === "configured_unverified"
        ? (zh ? "已填写，还没验证能不能连上" : "Filled in, connection not verified")
        : (zh ? "还没配" : "Not configured"),
    },
    {
      key: "report",
      label: zh ? "外部财报服务" : "Report service",
      value: row.reportStatus === "configured"
        ? (zh ? "已填写，还没验证能不能连上" : "Filled in, connection not verified")
        : (zh ? "还没配好" : "Not ready"),
    },
    {
      key: "library",
      label: zh ? "财报库" : "Report library",
      value: row.knowledgeReadable
        ? (zh ? "已绑定，可以读取" : "Bound and readable")
        : (zh ? "还没绑上" : "Not bound"),
    },
  ];
}
