# 会话账本归档：设计约束与体检结论

**Status: PROPOSED（未实施）** · 2026-09-12
**体检工具**：`scripts/report_session_ledgers.py`（严格只读，不移动/删除任何文件）
**背景**：账本是 append-only 的会话 transcript 权威，物理文件只增不减；本文件给出"若实施冷热分离/物理归档必须处理什么"的约束清单与一次真实体检基线。

---

## 1. 体检结论（2026-09-12，本机主实例）

| 分组 | 数量 | 大小 |
| --- | --- | --- |
| 账本文件合计 | 854 | 98.1 MB |
| 活跃（recency < 90 天） | 442 | 37.9 MB |
| 冷（≥ 90 天，未软归档） | 0 | 0 |
| 已软归档（`archived_at_ms` 非空） | 382 | 40.2 MB |
| 运行中守卫（running/queued/stopping/paused） | 0 | 0 |
| 无账本目录行（很可能为从未发消息的空会话） | 838 | — |
| 孤儿账本（有文件、目录无行） | 30 | 20.0 MB |

**判断**：当前体量小、无 90 天冷会话；首要候选是"已软归档会话"（40.2 MB），其次人工核对 30 个孤儿账本（20.0 MB）。**完整归档机制的工程成本（见 §2）明显高于当前收益**，建议保持"只读体检 + 按需人工处理"；机制化留待数据量或运维需求逼近时再做。

---

## 2. 设计约束清单（若实施归档，必须处理）

### A. 必须处理

1. **读写分离**：`turn_journal_path` 目前读写共用（`append_turn_event` 直接用同一解析结果）。归档"读回退"不得影响写目标——append 必须恒写活跃路径，新增独立读解析或 `for_write` 语义。
2. **序号水位（最高优先）**：`.watermark` 是旁车文件。归档必须与水位协同（读取方综合"归档 max seq + 活跃 watermark"），否则归档后新 append 从 seq=1 重来 → `ledgerSeq` 回退 → SSE/客户端断线重连游标崩坏。
3. **进程内缓存失效**：`_SEQUENCE_CACHE` / `_TERMINAL_SET_CACHE` / `_TURN_EVENTS_PREFIX_CACHE` / `_MKDIR_CACHE`（均在 `turn_journal.py`）与 `journal_bridge` 的 SSE 签名缓存都以路径字符串为 key，移动后必须显式失效/重建。
4. **锁一致性**：`_journal_file_lock` 用路径旁车 `.lock`；归档必须持同一 per-journal 锁（按 `project_root + session_id` 取锁，而非按路径），否则与 append 竞争。
5. **在飞守卫**：禁止归档 `latest_open_turn_id != ""` 或 `status ∈ {running, queued, stopping, paused}` 的会话（对齐 `agent_sessions.py` 会话归档守卫）。
6. **重开语义**：必须实现"写时搬回"或"读回退"——现状是账本被移走后 submit 会**静默新建空文件**（`load_turn_events` 返回空 → 历史为空 → turn 以空历史运行，不报错），并且 send-time ledger 对账会因"组装历史 ≠ 账本重建"而 fail-closed 拒绝发送。
7. **绕解析层直读者**：`conversation_index.py`（恢复/agentId 扫描，约 1962/2037/2079 行）、`maintenance_reset.py`（glob 删除候选，约 1084 行）、`agent_directory_service.py`（保留文件名清单）等必须与归档状态一致。
8. **catalog/目录投影**：`catalog_runtime._journal_inventory` 的 `journal_rel_path / size / mtime` 与 `journal_bridge` 签名在归档后要么指向归档位置、要么显式清空。
9. **冷选权威字段**：用 `sessions.recency_at_ms`（**勿用 `updated_at_ms`**——后台索引/对账会刷新它）+ `archived_at_ms IS NULL` + status 守卫；物理冷信号用 catalog `journal_mtime_ns`。

### B. 风险点

- **R1** 序号/水位回退——API/SSE 游标契约破坏（最高）。
- **R2** 重开静默失忆 / send-time 对账 fail-closed。
- **R3** 6+ 处进程内缓存失效遗漏。
- **R4** 直读路径（恢复/诊断/reset）与回退视图分裂。
- **R5** 双 root（sandbox 与 formal workspace）需两处一致。
- **R6** 双 DB 漂移：控制面 `recency_at_ms` vs catalog `last_active_at`，须固定单一权威。
- **R7** Windows：`_fsync_directory` 在 nt 上是 no-op；>260 字符路径需 `\\?\`；symlink/junction 跳过（参考 `prune_instance_storage`）。
- **R8** "物理 rewrite 例外"登记：`LEDGER_REWRITE_EXCEPTION_OWNERS` 目前是文字约定、无运行时校验；归档属新一类例外，需显式登记。

---

## 3. 可参考的现成先例

- `scripts/prune_codex_sessions.py`：默认 dry-run → `--apply` → 危险重写再加独立 flag；备份原始文件；被裁内容 gzip 落 `archived_lines/`；写结构化 report。
- `agent_sessions` 暂存迁移系列：staging 目录 + `shutil.move` + `manifest.json` + `restore_token` + 失败逆序回滚 + reparse-point 安全检查。
- `conversation_index` 的 `.session_deleted` tombstone：标记式守卫（可镜像为"archived"标记）。

---

## 4. 运行体检

```powershell
.\.venv\Scripts\python.exe scripts\report_session_ledgers.py
.\.venv\Scripts\python.exe scripts\report_session_ledgers.py --cold-days 60 --top 15
.\.venv\Scripts\python.exe scripts\report_session_ledgers.py --json > ledger_report.json
```

注意：`--project` 默认"脚本所在仓库根"——在工作树（worktree）里运行时请显式 `--project <主 checkout>`，否则会体检该工作树自己的空实例。
