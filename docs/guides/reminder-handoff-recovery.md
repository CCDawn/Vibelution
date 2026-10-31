# 原编号旧提醒交接恢复

用户确认的恢复方式是：展示当前来源，重新原生审批，核实原任务，继续原交接。
这不改变发送者安全证明或 `readyForCutover` 的判定，也不覆盖原授权记录。

## 契约与顺序

1. `history_source_preview` 取得本轮当前来源。新增 governed 动作
   `reminder_handoff_recover` 仅接收 `project_id`、`preview_id`；模型不能指定路径、
   原助理、批准标志或授权摘要。首次 `reminder_handoff_queue` 的行为保持不变。
2. 原生审批摘要冻结同一 preview 的来源、当前配置/注册快照摘要，以及原授权链 head。
   审批展示原 `operationId`、`syncId` 和“旧运行权限/发送者状态尚未证明”。
   重复生成摘要不能改绑已展示的 head。授权入口只针对本动作保留单次人工审批，
   `full_access`、yolo、会话授权和委派时间窗均不能跳过；plan 拒绝保持原样。
   真实请求的 request/call/session/agent/turn/arguments 身份经执行器现有 Context 复制
   进入工具线程；仅 `accept` 后的同一调用可单次执行。摘要本身、拒绝或过期均不授权。
3. 私有控制请求沿用 `initial_migration_queue`，仅提醒类别可带 `reauthorize: true`。
   旧调用仍使用原 closed schema；新字段不能进入其他类别。prepare 在真实本轮、
   preview、登记 revision、profile owner 和源文件 pin 下核对原 head、当前快照和身份。
4. 仅支持可证明未开始的恢复。原 attempt/result、业务 claim、归档、sync intent、
   回执、交接准备或不明 pending 任一存在均拒绝；普通日常提醒回执不是交接记录。
   Electron 检查其同一物理 store；native 在目标 profile owner 下检查业务产物。
5. 原 `intent.json` 字节保持不变。后继为独立不可变 `{schemaVersion,parentSha256,binding}`
   记录；所有读者经同一个严格 head 解析器读取。除本轮、登记 revision、来源授权摘要
   外，来源/目标身份、原编号及其他字段全部固定。分叉、孤链、坏 hash 或 pending 拒绝。
6. 审批 commit 只追加授权并立即返回排队回执。异步调度在该投递结束后建立原有迁移
   屏障，不在自己的审批内等待 main-control drain。刷新本地源缓存代际，防止旧缓存
   再进入执行；跨进程仍以同一原 `${syncId}.attempt` 的原子 `wx` 竞争唯一启动资格。
   该永久标记从不作为存活锁，也不删除、重置或自动重试。
7. worker 在 route/profile/source 锁内重新核对有效授权与当前源，再沿原流程执行。
   旧 claim 或回执未知的恢复不在本入口内强行重做。合作进程的排空不证明非合作旧发送者
   已停止；`queued` 和重新授权均不等于切换完成。

## 验证与失败处理

- 先验证后继链、head CAS、固定字段、产物拒绝和取消/崩溃边界，再验证审批摘要与本轮绑定。
- 验证私有协议只接受提醒恢复标志，普通 Session 和首次登记保留原语义。
- 验证审批返回后才启动调度、旧缓存失效、attempt 竞争只能有一个启动者。
- 完整检查后用 Launcher 加载当前代码；真实审批在完整预览可见后进行。
- 失败保留原编号和所有证据；未知结果查原回执。回退不删除后继、attempt 或用户数据。
