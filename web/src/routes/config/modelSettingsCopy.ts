export const MODEL_SETTINGS_COPY = {
  zh: {
    title: "模型", addService: "添加服务", modelIdentifier: "模型标识",
    services: "服务商", usage: "用途", searchProviders: "搜索服务商",
    addedModels: "已添加", availableModels: "可添加", discoverModels: "发现模型", save: "保存",
    hiddenProviders: "未启用的服务", backProviders: "返回服务商列表", backModels: "返回模型列表",
    outsideFilter: "当前编辑项不在筛选结果中，编辑内容已保留。", clearFilter: "清除筛选",
    subscription: "ChatGPT 订阅", models: "模型", connection: "连接",
    pendingDecision: "有尚未完成的模型编辑，请先完成或放弃更改。",
    usageHint: "普通聊天与个人助理继续使用各自会话中的模型选择；以下管理决策与交接用途。",
  },
  en: {
    title: "Models", addService: "Add service", modelIdentifier: "Model reference",
    services: "Providers", usage: "Usage", searchProviders: "Search providers",
    addedModels: "Added", availableModels: "Available", discoverModels: "Discover models", save: "Save",
    hiddenProviders: "Disabled services", backProviders: "Back to providers", backModels: "Back to models",
    outsideFilter: "The current item is outside the filter. Your edits are retained.", clearFilter: "Clear filter",
    subscription: "Manage subscription authorization", models: "Models", connection: "Connection",
    pendingDecision: "Finish the current model edit or discard your changes before saving.",
    usageHint: "Chat and Personal Assistant keep their per-conversation model selections. Manage decision and handoff models below.",
  },
} as const;
