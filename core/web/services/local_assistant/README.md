# 本机助理开发任务

本模块为 Launcher 个人助理提供第一方权限策略，执行仍归原生
`ExternalAgentTaskService`、Session、Journal 和 worker。第三方 MCP 的开关、白名单、
只读默认和审批规则保持独立。

- `launcher_assistant_authority` 在固定用户 profile 中建立私有凭据；只由持有
  host-owner 锁的真实助理 bootstrap 初始化。后端只读验证，不使用客户端自报来源提权。
- `local_assistant_tasks` 复用现有 route 和任务生命周期；每次请求验证控制凭据和
  助理凭据，原生任务记录只保存凭据摘要。禁用、撤销或轮转后旧摘要失效。
- `service` 为普通写任务创建 `codex/assistant-*` worktree，保留用户明确拒绝、
  团队/Companion/受保护身份边界。任务完成后保留变更供审查，不自动发布。
- `runtime` 从后端拥有的 task→session→agent 关系解析临时工具与工作目录；消息
  metadata 或 `launcher-assistant:` 请求前缀都不能成为权限依据。
- `policy` 和 `consent` 在现有最终工具执行授权入口放行普通文件编辑及本地测试、
  构建和 Git 操作。对外发布、删除、权限扩张、任意脚本与越界访问仍走原生审批。

测试和构建会执行项目代码；这是任务授权策略，不是操作系统沙箱。私有凭据证明
同一 OS 用户下的持有者，不声称能隔离该用户下任意恶意原生程序。

回归入口为 `tests/test_local_assistant_*.py` 和
`tests/test_launcher_assistant_authority.py`；实际模型开发验收由
`scripts/acceptance_local_assistant_development.py` 使用隔离配置和数据执行。
