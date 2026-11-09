# 会话切换延迟：结构性优化方案

> 状态：方案（部分已落地）
> 归属：`core/web/services/session/`（select / projection）、`web/src/routes/chat/`（detail query）
> 触发：运行中切换会话明显卡顿，空闲时正常

## 1. 已确认的成因结构

切换会话不是一次增量操作，而是「一次串行化写 + 多次全量投影」的组合。运行中卡、空闲不卡，是因为运行路径持续占用同一把跨进程锁。

### 1.1 主因：跨进程 `chat_state` 文件锁争用

| 角色 | 位置 | 行为 |
| --- | --- | --- |
| 写路径 | `persist.py` `_commit_session_turn_runtime_state` | `with s._CHAT_STATE_LOCK` 内 load → merge → save，被工具结果、阶段结算、失败结算等 6 处调用 |
| 切换路径 | `conversation_index.py` `select_chat_session` | 同样在 `with s._CHAT_STATE_LOCK` 内做 load → metadata 修复 → save |

两者争用同一个 `.chat_state.lock`。锁超时设为 180s（`chat_state.py`），本身就说明设计上预期这里会长时间等待。

**这条是「运行时卡顿、空闲正常」现象的直接解释。**

### 1.2 放大项：一次切换触发多次全量 detail 组装

1. `/select`（前端 `Prefer: respond-async` → lightweight）
2. 主 detail GET（此前默认 `includeSecondary=true`）
3. SSE `/events?initial=light` 在 `_SESSION_STREAM_EXECUTOR`（max_workers=8）里再组装一次
4. `_build_session_detail_from_summary` 串行执行 ledger 序列、turn control、active task、live output、runtime metrics、agent 快照、secondary 侧列表

### 1.3 放大项：每次 select 深拷贝全量 Agent 注册表

`_agent_lookup_for_conversations()` 无参调用走 `load_state()`，`repair_store.py` 对完整 registry 做 `_copy_json_value` 深拷贝，再逐个投影。

### 1.4 放大项：会话列表缓存失效

select 时只要 `metadata_changed` 就 `_invalidate_session_list_cache()`，下一次 3s 轮询全量重建列表投影。

## 2. 本次已落地的改动

### 2.1 分段计时埋点（可回退）

- `conversation.session.switch.timing`：`surface` / `stageDurationsMs` / `totalMs`，**锁等待与锁持有分成两个字段**（`chatStateLockWaitMs` / `chatStateLockHoldMs`）
- `conversation.session.detail.timing`：`includeSecondary` / `sessionRunning` / `windowRequested` / 分段耗时
- 契约由 [tests/test_session_switch_timing.py](../../tests/test_session_switch_timing.py) 固定

只有把 wait 和 hold 分开，才能区分「切换排在运行写之后」和「锁内逻辑本身慢」。合并成单一是本次排障最大的盲区来源。

### 2.2 select 的 Agent 查询改为定向

`select_chat_session` 先读一次行，用该会话声明的 bound ids + direct-session owner 做定向 `load_agent_records`；闭包为空时保留原来的全量回退，未绑定 legacy 行的行为不变。

### 2.3 detail 主路径轻量化 + 尾随补全

- 主 detail 查询固定 `includeSecondary=false`，首屏不再等待 inbox / governance / group / next-state 读取
- 新增 `sessionSecondaryQuery`：带 `transcriptScope=none`、`messageLimit=1` 的尾随补全，只把侧栏字段合并回已绘制的 detail（`mergeSessionDetailSecondaryLists`），不动 transcript 和 window
- 侧栏数据仍然可达，只是不再阻塞首帧

## 3. 尚未落地（需要单独任务）

### 3.1 把 select 的 metadata 修复移出锁（收益最高，风险也最高）

当前 metadata 修复、directory sync 都在锁内。可选路径：

1. 锁内只做「读 + 判定是否需要修复」，把实际修复提交挪到锁外单写事务
2. 或者给 metadata 修复单独的业务锁，与 turn 写路径解耦

风险：会改变写路径的原子性假设，必须核对 `_ensure_conversation_agent_metadata` 依赖的读后写一致性，以及 directory bridge 的顺序约束。**不建议在没有实测数据前动。**

### 3.2 ledger events 独立序列

ledger 事件应使用自己的序列/锁，不与 `chat_state` 争用。需要先确认 ledger 与 chat_state 之间是否存在真实的跨模块顺序依赖。

### 3.3 运行期轮询与锁的错峰

`ACTIVE_SESSION_DETAIL_POLL_MS=3000`、索引轮询 3s、后台同步 5s 三者同时撞锁。可在运行中降低索引轮询频率，或把 detail 轮询改成事件驱动。

### 3.4 SSE 线程池与首帧组装

`_SESSION_STREAM_EXECUTOR` 只有 8 个 worker，每次建流都排一次 detail 组装。快速连点切换会堆积。

## 4. 验证顺序建议

1. **先看数据**：用 `conversation.session.switch.timing` 采样，确认 `chatStateLockWaitMs` 在总耗时中的占比
2. 若占比高 → 优先做 3.1（锁粒度拆分）
3. 若占比低、`projectionMs` 高 → 优先做 3.2 + 3.4
4. 每步都以「切换体感 + 埋点分位数」双重验收，不只看均值

## 5. 明确不做

- 不为切换卡顿单独引入第二套会话状态权威
- 不把 detail projection 变成写入者
- 不用「先关掉 secondary 渲染」掩盖后端成本（本次是让数据晚到，不是丢数据）
