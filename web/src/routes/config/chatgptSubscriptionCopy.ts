export const CHATGPT_SUBSCRIPTION_COPY = {
  zh: {
    heading: "ChatGPT 订阅", existingPlan: "使用已有套餐", title: "ChatGPT",
    subtitle: "在 Vibelution 中使用你的 ChatGPT 套餐", connected: "已连接", signedOut: "未连接",
    pending: "等待授权", reauth: "需要重新登录", quota: "额度受限", unavailable: "暂不可用", checking: "正在读取连接状态…",
    connectDescription: "通过浏览器登录并授权，无需填写 API Key。", connect: "Continue with ChatGPT", browser: "在默认浏览器中继续",
    waitingTitle: "请在浏览器中完成授权", waitingBody: "完成后会自动更新连接状态，你也可以取消并稍后再试。",
    exchangingTitle: "正在确认浏览器授权", reopen: "重新打开浏览器", openAuthorization: "打开官方授权页面", manualBrowser: "浏览器未自动打开，请点击官方授权页面继续。",
    cancelLogin: "取消授权", relogin: "重新登录", retry: "重试", refresh: "刷新", usage: "管理用量", usageFallback: "打开官方用量页面",
    browserAuth: "浏览器授权", plan: "使用 ChatGPT 套餐", disconnect: "断开连接", disconnectTitle: "断开 ChatGPT 连接？",
    disconnectBody: "本机授权凭据将被移除。已选择的订阅模型会暂不可用，你可以重新连接或手动选择其他服务。",
    cancel: "取消", disconnected: "已断开连接。原有模型选择保留，不会自动切换服务。",
    localDisconnected: "已移除本机授权凭据；远端撤销尚未确认，请在 ChatGPT 官方账户页面检查授权状态。原有模型选择保留。",
    securityNote: "授权凭据安全保存在本机。额度用完时暂停并提示，不会自动产生 API 费用。",
    authorizationNote: "已连接表示本机授权成功；模型是否可用以实际调用结果为准。",
    modelsTitle: "账户可用模型", modelsLoading: "正在读取账户可用模型…", modelsEmpty: "账户尚未返回可用模型", modelsEmptyBody: "可以稍后刷新；已有服务和模型选择保持不变。",
    modelsNote: "模型来自当前账户的实际返回。添加后可在普通聊天与个人助理中选择，不会改变原有默认。",
    selected: "已选择", notSelected: "未选择", selectModel: "选择", addModels: "添加所选模型", added: "所选模型已加入可选列表。原有默认保持不变。",
    addFailed: "模型暂未保存", addFailedBody: "所选模型仍保留，请重试。", keepSelection: "已有模型选择仍保留；不会自动改用收费 API。",
    authErrorTitle: "登录已失效，请重新连接", authErrorBody: "已有模型选择仍保留；完成授权后即可继续使用。不会自动改用收费 API。",
    quotaTitle: "当前 ChatGPT 套餐额度受限", quotaBody: "请等待额度恢复，或手动选择其他已配置模型。Vibelution 不会自动切换到收费 API。",
    networkTitle: "暂时无法连接 ChatGPT", networkBody: "请检查网络后重试。原有服务和模型选择不受影响。",
    expiredTitle: "本次登录已过期", expiredBody: "请重新打开官方授权流程；原有账户与模型选择保持不变。",
    declinedTitle: "本次登录未完成", declinedBody: "可以重新登录并完成授权。原有账户与模型选择保持不变。",
    identityTitle: "登录账户与原账户不一致", identityBody: "原连接已保留，请使用原账户重新登录。",
    storageTitle: "暂时无法安全读取或保存授权", storageBody: "请检查本机安全凭据存储后重试。模型选择保持不变。",
    genericTitle: "ChatGPT 连接暂不可用", genericBody: "请稍后重试。原有服务和模型选择保持不变。",
    reasoning: "推理深度", context: "上下文", tokens: "tokens",
  },
  en: {
    heading: "ChatGPT subscription", existingPlan: "Use your existing plan", title: "ChatGPT",
    subtitle: "Use your ChatGPT plan in Vibelution", connected: "Connected", signedOut: "Not connected",
    pending: "Awaiting authorization", reauth: "Sign in again", quota: "Usage limited", unavailable: "Unavailable", checking: "Checking connection…",
    connectDescription: "Sign in and authorize in your browser. No API key required.", connect: "Continue with ChatGPT", browser: "Continue in your default browser",
    waitingTitle: "Complete authorization in your browser", waitingBody: "The connection updates automatically when you finish. You can also cancel and return later.",
    exchangingTitle: "Confirming browser authorization", reopen: "Reopen browser", openAuthorization: "Open official authorization page", manualBrowser: "Your browser did not open automatically. Open the official authorization page to continue.",
    cancelLogin: "Cancel authorization", relogin: "Sign in again", retry: "Retry", refresh: "Refresh", usage: "Manage usage", usageFallback: "Open official usage page",
    browserAuth: "Browser authorization", plan: "Uses your ChatGPT plan", disconnect: "Disconnect", disconnectTitle: "Disconnect ChatGPT?",
    disconnectBody: "Local authorization credentials will be removed. Selected subscription models will be unavailable until you reconnect or manually select another service.",
    cancel: "Cancel", disconnected: "Disconnected. Existing model selections are retained; no service is switched automatically.",
    localDisconnected: "Local authorization credentials were removed. Remote revocation is not confirmed; check authorization in your official ChatGPT account. Existing model selections are retained.",
    securityNote: "Authorization credentials are stored securely on this computer. Usage limits pause requests and show a notice; no automatic API charges.",
    authorizationNote: "Connected confirms local authorization. Model availability is confirmed by an actual request.",
    modelsTitle: "Account models", modelsLoading: "Reading available account models…", modelsEmpty: "No available models returned yet", modelsEmptyBody: "Refresh later. Existing services and model selections are retained.",
    modelsNote: "Models are returned by the current account. Added models can be selected in chat and the personal assistant; existing defaults are retained.",
    selected: "Selected", notSelected: "Not selected", selectModel: "Select", addModels: "Add selected models", added: "Selected models were added to the available list. Existing defaults are retained.",
    addFailed: "Models were not saved", addFailedBody: "Your selection is retained. Please retry.", keepSelection: "Existing model selections are retained. No automatic switch to paid API usage.",
    authErrorTitle: "Authorization expired. Sign in again", authErrorBody: "Existing model selections are retained and recover after authorization. There is no automatic switch to paid API usage.",
    quotaTitle: "Your ChatGPT plan is currently usage limited", quotaBody: "Wait for usage to recover, or manually select another configured model. Vibelution will not automatically switch to a paid API.",
    networkTitle: "Cannot reach ChatGPT right now", networkBody: "Check your network and retry. Existing services and model selections are retained.",
    expiredTitle: "This sign-in attempt expired", expiredBody: "Start official authorization again. Your previous account and model selections are retained.",
    declinedTitle: "Sign-in was not completed", declinedBody: "Sign in again to complete authorization. Your previous account and model selections are retained.",
    identityTitle: "The signed-in account differs from the original", identityBody: "The original connection was retained. Sign in with the original account.",
    storageTitle: "Cannot securely read or save authorization", storageBody: "Check local secure credential storage and retry. Model selections are retained.",
    genericTitle: "ChatGPT connection is unavailable", genericBody: "Please retry later. Existing services and model selections are retained.",
    reasoning: "Reasoning", context: "Context", tokens: "tokens",
  },
} as const;

export type SubscriptionCopy = typeof CHATGPT_SUBSCRIPTION_COPY[keyof typeof CHATGPT_SUBSCRIPTION_COPY];

export function subscriptionErrorContent(code: string, copy: SubscriptionCopy) {
  if (["reauth_required", "permission_missing", "signed_out", "invalid_identity"].includes(code)) return { title: copy.authErrorTitle, body: copy.authErrorBody, recovery: "login" as const };
  if (code === "rate_limited") return { title: copy.quotaTitle, body: copy.quotaBody, recovery: "usage" as const };
  if (["network", "timeout", "upstream_unavailable"].includes(code)) return { title: copy.networkTitle, body: copy.networkBody, recovery: "retry" as const };
  if (code === "login_expired") return { title: copy.expiredTitle, body: copy.expiredBody, recovery: "login" as const };
  if (["login_declined", "registration_incomplete"].includes(code)) return { title: copy.declinedTitle, body: copy.declinedBody, recovery: "login" as const };
  if (code === "identity_mismatch") return { title: copy.identityTitle, body: copy.identityBody, recovery: "login" as const };
  if (code.startsWith("storage_")) return { title: copy.storageTitle, body: copy.storageBody, recovery: "retry" as const };
  return { title: copy.genericTitle, body: copy.genericBody, recovery: "retry" as const };
}
