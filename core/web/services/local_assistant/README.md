# 本机助理开发任务

本模块为 Launcher 个人助理提供第一方权限策略，执行仍归原生
`ExternalAgentTaskService`、Session、Journal 和 worker。第三方 MCP 的开关、白名单、
只读默认和审批规则保持独立。

- `launcher_assistant_authority` 在固定用户 profile 中建立私有凭据；只由持有
  host-owner 锁的真实助理 bootstrap 初始化。后端只读验证，不使用客户端自报来源提权。
- `local_assistant_tasks` 复用现有 route 和任务生命周期；每次请求验证控制凭据和
  助理凭据，原生任务记录只保存凭据摘要。禁用、撤销或轮转后旧摘要失效。
  本机传输使用五分钟续约窗口，容纳模型慢响应；第三方租约不变，到期巡检仍停止任务。
- `service` 为普通写任务创建 `codex/assistant-*` worktree，保留用户明确拒绝、
  团队/Companion/受保护身份边界。任务完成后保留变更供审查，不自动发布。
- `runtime` 从后端拥有的 task→session→agent 关系解析临时工具与工作目录；消息
  metadata 或 `launcher-assistant:` 请求前缀都不能成为权限依据。
- `legacy_cleanup` 仅供 Launcher 清理升级前的委派任务。私有
  `/api/local-assistant/v1/external-agent/legacy-tasks/{task_id}/cleanup[/preview]`
  同时验证 control token、当前 Launcher 凭据和原 task capability，并要求原请求属于
  Launcher 委派、任务已终止且 Session 独占。它复用现有清理响应，不迁移传输命名空间，
  不提供普通外部清理接口，也不从旧记录推断工作区所有权。原 task 路径原子替换为去掉
  结果和 Session 关联的终态凭据，让原 SDK 的幂等重放仍返回原任务，不再执行。
  若原生运行记录和同项目目录记录均已不存在，且无活动、共用引用或遗留内容文件，
  只压缩旧 task 记录并保留并发锁；不再调用 Session 删除，也不据此删除未知归属文件。
- `policy` 和 `consent` 在现有最终工具执行授权入口放行普通文件编辑及本地测试、
  构建和 Git 操作。对外发布、删除、权限扩张、任意脚本与越界访问仍走原生审批。
  普通命令可用最多 16 段 `&&` 连续执行，每段独立校验。Windows 支持任务目录内的
  `cd [/d]` 和有限 `dir` 检查；切换目录后按新目录验证路径和同名可执行文件遮蔽。
  `cd` 目标必须已经存在；目录列举不支持通配符、递归和跟随越界链接。可信 `ls`、
  `pwd` 可单独调用，Windows 混用它们的命令链仍保留审批，避免 cmd/Bash 路由差异。
  命令只支持无转义的双引号分组；单引号分组、引用内 `&&`、其他 shell 操作符、
  重定向、替换和环境变量展开均保留审批。

测试和构建会执行项目代码；这是任务授权策略，不是操作系统沙箱。私有凭据证明
同一 OS 用户下的持有者，不声称能隔离该用户下任意恶意原生程序。

回归入口为 `tests/test_local_assistant_*.py` 和
`tests/test_launcher_assistant_authority.py`；实际模型开发验收由
`scripts/acceptance_local_assistant_development.py` 使用隔离配置和数据执行。
