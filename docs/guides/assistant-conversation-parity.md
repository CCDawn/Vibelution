# Launcher 对话与普通聊天的行为对齐

目标：发送到正式消息回读之间始终保留消息回显，复用普通聊天的提交、确认、回读和控制结果处理；Launcher 保留独立进程、固定会话和封闭 IPC。

| 事实 | 权威与写入者 | 前端派生与更新 |
| --- | --- | --- |
| 正式消息、执行状态 | 原生 Session / Journal / worker | 普通 HTTP 或 Launcher IPC 读取同一 DTO；按 ledger 合并 |
| 未确认提交 | 原请求 ID 与提交快照 | 临时用户行只用于回显，不能证明接收；正式消息按提交 ID 替换 |
| 排队接收 | 原生 queued receipt / queuedTurns | 接收回执可即时投影队列；不能当作已执行 Turn |
| 实时正文 | 原生 assistant_delta / Journal | 共用序列门、append 解码、active layer 和消息窗口合并；Launcher 适配 Unicode offset / connection epoch |
| 私有通信、生命周期 | Electron main 与 assistant runtime | 凭据不进 renderer；不增加通用代理或普通项目 API 权限 |

实施与验收：

1. 抽取普通聊天已有的提交投影，双方共用开始、接收、排队与失败删除；慢回读、旧详情不能移除未落地的本地消息。
2. 接收证据回读注入 transport 与 query key；普通聊天默认保持 HTTP，Launcher 只用 IPC。未知结果先核对原请求，保持同一 ID，不盲目重发。
3. stop / guidance 即时应用成功返回的 detail；切版本取消旧读取并整体替换，保留失败与身份边界；继续和重新生成保持原请求恢复。
4. 保留已共用的队列、流式、附件分类及引用身份逻辑，核查请求期间新增草稿和引用不会被旧完成回调清掉。
5. 回归覆盖延迟 ACK、延迟/陈旧 detail、正式替换去重、明确拒绝、丢 ACK、排队、停止/引导、版本切换与流式恢复。实际页面使用隔离桥模拟慢读取，不向用户真实会话发送测试消息。

能力边界：历史编辑继续显示“编辑为新消息”，不虚构 edit-resubmit 动词；会话/知识搜索、文件读取、secret 和队列遵守现有 IPC 与 capability 门。普通 Session 后端和 Companion 核心不改。

开发/正式模式采用同一前端逻辑。无 API/schema 或依赖变更，属于行为修复；运行中旧页面需要加载新前端产物，未授权重启不打断活动任务。

实现记录：普通聊天与 Launcher 共用 `sessionSubmitProjection`；接收证据回读支持注入 detail reader / query namespace，IPC 超时只结束前端等待，不宣称取消原生请求。Launcher 停止、引导应用原生回包；重新生成保留历史并复用回读恢复，切版本取消旧详情请求。附件上传结果与引用快照比较复用普通聊天函数。ACK 后等待层从 sending 转入已发送阶段，不覆盖更早到达的正文。

日志决定：保持原生 Session 的提交、接收、Journal、停止与引导日志权威；本次临时回显不产生第二份 transcript，也不为日志增加 renderer 到普通 HTTP 的通道。验证仅记录请求身份、时序和数量，不保存用户消息正文或凭据。

2026-11-06 隔离页面验证：实际 LauncherAssistantRoute + ConversationView，假桥确认延迟 300ms、详情延迟 2500ms；原生 Electron 窗口完成一次发送，394 个动画帧采样中空白帧 0，气泡峰值及最终气泡数均为 1。该验证不调用真实模型、不向用户会话写入；正式运行窗口是否已加载新产物单独判断。
