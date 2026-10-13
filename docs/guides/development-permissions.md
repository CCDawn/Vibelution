# 开发权限、运行刷新与验收交接

常规编辑、测试和构建在任务 worktree 中连续完成。产品生命周期仍由 Electron main Launcher 执行；开发检查不能授予权限，也不能把测试通过改写成运行验收通过。

## 只读入口

使用项目已验证的 Python，从任意已登记 checkout 调用：

```powershell
<PYTHON> scripts/development_preflight.py --project <PROJECT> --instance-id <EXACT_INSTANCE_ID> --files <CHANGED_FILES>
```

`EXACT_INSTANCE_ID` 来自既有 `list_branch_instances` 投影，不能用模糊分支名或任意路径替代。工具复用 `core.infrastructure.branch_workspace`，重新核对所属仓库、checkout 和分支，输出工作树权限建议、依赖只读范围、刷新提示和未完成的验收层。它不创建目录、不读密钥、不发 HTTP 请求、不修改权限或运行状态。

需要准备隔离实例的生命周期交接时添加 `--operation start|stop|restart`。输出中包含既有 Launcher IPC 请求：`schemaVersion: 1`、`branch-instances/<operation>`、`body.instanceId`。**这只是交接说明，不会执行请求。** 只有确切存在的 `codex/*` 隔离 worktree 可生成交接；main、未检出分支、遗留目录、任意 Shell 和强制停止均拒绝。主实例只允许只读检查。

退出码：`0` 表示检查/交接生成成功，`2` 表示目标、身份或路径检查失败。`0` 不表示批准、健康、代码加载或用户验收成功。`readOnly=true`、`executionAttempted=false` 和 `approvalGranted=false` 明示该边界。新增入口不改变现有 Launcher、MCP 或前端 API；当前 MCP managed-Agent gateway 不具备 Launcher 执行能力，不冒充该能力。

## 权限方案

本任务核验到的宿主策略是 `approval_policy=never`、`danger-full-access`。常规开发已有文件权限；增加 writable roots 不能解决危险命令判定。静态检测曾把同一 PowerShell 脚本中的 URL 与 `Start-Process` 组合判为危险，而 `never` 没有人工审批出口。当前会话的有效策略来自宿主，不能通过修改配置文件追溯改变。

未来开发会话可由操作者在受支持的 Codex 设置中采用下面的配置。它是**可审阅方案，未由工具自动应用**；管理策略、项目可信状态和宿主优先级仍需核对。

```toml
approval_policy = "on-request"
approvals_reviewer = "user"
sandbox_mode = "workspace-write"

[sandbox_workspace_write]
writable_roots = ["<EXACT_TASK_WORKTREE>", "<EXACT_TASK_SCRATCH>"]
network_access = true
```

- worktree 与 scratch 使用只读入口输出的确切绝对路径，不能授权整个磁盘、用户目录或所有 worktree。
- 共享 `.venv` 和其它任务的依赖保持只读；依赖变更需要已验证的物理任务环境，不创建 junction。
- Git common-dir 与 `.codex` 等受保护路径遵循宿主独立保护；这份配置不保证 `git commit` 自动获准。
- 若确需命令规则，只针对可审阅的固定工具和参数，带官方 `match/not_match` 检查；不添加泛化 PowerShell、Python、curl 或任意 Launcher action 的 allow。
- 配置/规则变更可能需要新会话或应用加载；不自动重启用户 Codex，不承诺配置能撤销平台级禁止。

官方依据：[减少审核量](https://learn.chatgpt.com/docs/sandboxing/auto-review#reduce-review-volume-without-weakening-security)、[审批与沙箱](https://learn.chatgpt.com/docs/config-file/config-advanced#approval-policies-and-sandbox-modes)、[命令规则](https://learn.chatgpt.com/docs/agent-configuration/rules)。

## 被拒绝的动作

工具拒绝某个运行操作后，保留动作、对象、原错误与已完成证据。继续不依赖该动作的编辑、测试和构建；受影响的运行验收保持待完成。

不能将已拒动作拆成多个调用、换语言包装、切换工具或新增执行入口重试。有效宿主为 `never` 时，本会话没有审批出口；准备具体对象与正式操作说明，交给受支持的宿主审批/操作者流程。没有审批回执不能伪造为已批准。

正常的已授权生命周期操作复用 [桌面调试指南](desktop-debugging.md) 中的官方 Launcher/可信 IPC，遵循 [Launcher ADR](../adr/0009-launcher-control-plane-lives-in-electron-main.md)。执行前 Launcher 重新核对实例、活动任务和 admission；操作者触发与 Agent 自动触发的 provenance 不能混用。保留原生 `commandId`、`generation` 和最终 settlement。响应丢失先读回执和状态，不能盲目再次 restart。

## 连续开发与等价验收

1. 在任务 worktree 聚合一批改动，写入前走既有 claim/preflight；只读入口不代替该检查。
2. 以最窄相关测试反馈，前端完成前过类型检查和 VUI 合同；预览只代表预览，不证明正式运行加载了该版本。
3. 最终完整 selector 由 `task_closeout.py` 执行。复用 manifest 先核对内容指纹、验证面与最新 main，规则见 [loop.md](loop.md#证据复用规则避免无意义重跑)。
4. 仅在真正需要验证运行行为时安排官方刷新。不得因 `refreshHint=none` 自动豁免 owner 的运行判断；未知文件和未给文件列表均要求审查。
5. 分别核验服务归属与 health、实际前后端版本、浏览器真实操作、业务结果。任一层缺证据仍待验收；健康、构建或测试成功不能替代后面的层。

## 事实权威与更新

| 事实 | 权威 | 本入口的作用 |
| --- | --- | --- |
| checkout、实例映射 | Git / `branch_workspace` 投影 | 只读选择并重新核对 |
| 宿主有效权限与审批 | Codex 当前宿主 | 明示无法从本工具观察或授予 |
| 运行生命周期、原生回执 | Electron main Launcher | 准备既有 IPC 交接，不执行、不写状态 |
| 验证可复用性与合入 | `task_closeout.py` / manifest | 提示沿用原有核对，不建立第二套验证状态 |
| 运行版本、真实用户行为 | 新鲜 runtime / browser / business 证据 | 默认未验证，待实际取证 |

输出带 `observedAt`，属于瞬时检查结果。checkout、分支、实例或权限改变后重新检查；审批仍不能替代执行时的 Launcher 校验。没有新 registry、队列、执行代理或权限持久化。
