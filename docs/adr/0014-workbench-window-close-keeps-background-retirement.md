# 0014. Workbench 窗口及时关闭，Launcher 持续确认后台清退

- Status: Accepted
- Date: 2026-10-26
- Decision owner: Operator
- Related: [0009](0009-launcher-control-plane-lives-in-electron-main.md), [0012](0012-launcher-owns-personal-assistant-runtime.md)

## Context

Launcher 助理迁移的隔离合入检查发现，现有原生关闭测试要求在约两秒内同时完成 Job、输出管道与 TCP listener 清退。未改动主分支的临时对照也复现了失败：Job accounting 已归零，原生 root process wait 尚未完成，两路 drain 未完成，原 PID 的端口仍监听。不能把 `process.kill(pid, 0)` 返回不存在解释为所有资源已经清退。

Windows 强制终止涉及异步 I/O 的取消与完成，不能根据发出终止请求就确认资源已结束，见 [TerminateProcess 文档](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-terminateprocess)。2026-10-26 用户明确选择“窗口及时关闭，后台持续回收并明确显示未完成”。

## Decision

窗口响应预算只约束窗口关闭授权与 ACK，不承诺 OS 在相同时间内完成所有资源清退。Electron 保持既有托盘驻留，Launcher 负责后台清退；窗口 ACK 和后台确认是两个独立事实。

放行窗口前，先记录并持久化 `desiredState=closed / phase=stopping`，保留原 PID、创建时间、可执行文件、端口及关闭请求关联。Launcher 沿用既有“停止中”投影；普通状态刷新或窗口消失不得覆盖待确认状态。

后台只回收已捕获、受原生 owner 管理的精确 Job/进程身份，复用已有生命周期命令、退休闭包和有界重试。不得根据后来复用的 PID 或端口杀进程，不引入通用命令执行器、第二套进程注册表或新常驻服务。单次命令超时不会把尚未完成的关闭记为成功，后台恢复保留原意图。

确认 Job、输出 drain、目标端口及本次拥有的前端构建进程全部清退后，才清除句柄并记录 closed。完成写入继续使用现有 epoch/身份校验，旧回收结果不得覆盖新的 start/restart。重启后仅凭持久 stopping 不能伪造完成；须经现有身份校验与恢复 owner 复核。

## Alternatives

- 所有资源必须在两秒内清退：拒绝作为窗口关闭前提；实际主分支对照已证明本机存在更长的退出窗口。
- 忽略端口或 drain、超时即 closed：拒绝，会把仍存活或未排空的资源隐藏成成功。
- 只提高超时、让窗口持续等待：拒绝，会继续增加用户等待和重复关闭操作。
- 新建清退服务或重新扫描 PID 树：拒绝，增加维护面并削弱既有身份边界。

## Consequences

窗口能及时响应，后台状态保持真实，用户可在 Launcher 查看未完成的清退。测试须分别证明窗口响应预算和最终资源确认，保留两者之间的 pending 证据；旧的“全部资源必须在窗口预算内结束”测试不再是产品契约。最终确认、授权、身份隔离和无控制台要求均不放宽。

本决策不授权正式运行数据操作、安装或发布，不修改普通 Session 核心，也不替代 Launcher 助理真实模型及旧数据迁移验收。
