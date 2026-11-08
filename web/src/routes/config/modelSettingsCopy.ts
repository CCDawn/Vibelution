export const MODEL_SETTINGS_COPY = {
  zh: {
    services: "模型服务", usage: "模型用途", searchProviders: "搜索厂商或模型",
    hiddenProviders: "未启用的服务", backProviders: "返回服务商列表", backModels: "返回模型列表",
    outsideFilter: "当前编辑项不在筛选结果中，编辑内容已保留。", clearFilter: "清除筛选",
    subscription: "管理订阅授权", models: "模型", connection: "连接设置",
    pendingDecision: "有尚未完成的模型编辑，请先完成或放弃更改。",
    usageHint: "普通聊天与个人助理继续使用各自会话中的模型选择；以下管理决策与交接用途。",
  },
  en: {
    services: "Model services", usage: "Model usage", searchProviders: "Search providers or models",
    hiddenProviders: "Disabled services", backProviders: "Back to providers", backModels: "Back to models",
    outsideFilter: "The current item is outside the filter. Your edits are retained.", clearFilter: "Clear filter",
    subscription: "Manage subscription authorization", models: "Models", connection: "Connection",
    pendingDecision: "Finish the current model edit or discard your changes before saving.",
    usageHint: "Chat and Personal Assistant keep their per-conversation model selections. Manage decision and handoff models below.",
  },
} as const;
