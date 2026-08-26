# 测试回归基线清理

> **Status**: `implemented`
>
> **Owner**: `codex-root-test-baseline-20260826`
>
> **Claim/branch/worktree**: `claim-1f4b93c94e5d` · `codex/test-regression-baseline-recovery` · `.worktrees/test-regression-baseline-recovery`
>
> **Scope**: 修正已证实过期的 Pet 测试契约；让完整收集失败的本地、远端和 CI pytest 命令显式使用 `--maxfail=0`；统一测试文档到项目 `.venv` 解释器与 selector-first 入口。Runtime Manager 只保留本轮复核，不再修改已绿的当前契约。
>
> **Supersedes**: 无。本计划把 2026-08-26 的只读测试审查结论转为一次有限的基线恢复。
>
> **Implementation link**: `codex/test-regression-baseline-recovery` 已完成实现；本文件归档保留验证边界和延后项。
>
> **Validation**: `tests/test_pet_web_actions.py`、`tests/test_runtime_manager.py`、`tests/test_select_tests.py`、`tests/test_remote_test_runner.py`、`tests/test_ci_workflow_contract.py` 共 340 项通过；selector/remote/CI 命令断言通过。
>
> **Close condition**: 完整回归入口不再被 `pytest.ini` 的默认 `-x` 截断，Pet 测试与当前产品契约一致，且本计划所列的目标验证通过。

## 目标与证据

`pytest.ini` 的 `addopts` 保留 `-x`，用于快速本地定位；但面向完整回归审计的入口必须显式用 `--maxfail=0` 覆盖它。pytest 官方文档定义 `-x` 为首错停止，`--maxfail` 为失败上限，因此这不是删除 fail-fast，而是把两种意图分开。

已复现的旧测试契约如下：

1. `tests/test_pet_web_actions.py` 把 `chdir(tmp_path)` 当作 Pet 存储根，并断言 `tmp_path/workspace/memory/pet_info.json`。产品现在通过正式项目 workspace resolver 落盘；测试应隔离 resolver，并断言该正式语义。该 API 测试还不应依赖工作树里预先构建的 `web/dist`。
2. 复核当前 `main@581300546` 时，`tests/test_runtime_manager.py` 的 265 项均通过，且此前 Python 控制面已在提交 `30f893304` 退役。报告中的四项旧断言不再存在；本任务不重复修改它们。

## 推荐实施路径

1. 先在测试中注入临时 Pet 存储与临时前端 dist，只验证 `/api/pet/actions` 的 API 行为；不修改 Pet 或 web runtime 产品代码。
2. 在 selector 的 local parallel/serial 常量、remote distributed 命令构造和 CI coverage pytest 命令添加 `--maxfail=0`，并补强相应的命令契约测试。
3. 更新 `tests/README.md` 与 development standard §11：默认入口先运行 selector；完整 Python `not serial` 回归使用 `.venv\\Scripts\\python.exe -m pytest ... --maxfail=0`。保留显式 `-x` 作为定位命令。

## 保护边界与延后项

- 保留 `pytest.ini` 的默认 `-x`；不把所有 pytest 调用机械改为 `--maxfail=0`。
- 不修改产品 Pet storage、Electron lifecycle、outbox/ledger 生命周期或 Challenge Cup 运行状态。
- 不实现 import 图传递闭包、known-failures/baseline snapshot 账本、定时 CI schedule 或 closeout 缓存。基线运行的频率和成本仍需另行决定。
- 不触发远端 workflow 或 push；CI YAML 只做静态契约修正。

## 验证顺序

```powershell
& '.\.venv\Scripts\python.exe' -m pytest `
  tests/test_pet_web_actions.py `
  tests/test_runtime_manager.py `
  tests/test_select_tests.py `
  tests/test_remote_test_runner.py `
  tests/test_ci_workflow_contract.py -q --maxfail=0

& '.\.venv\Scripts\python.exe' tests/select_tests.py `
  --changed-file core/pet_system/utils/storage.py --commands-only
```

不在本任务重跑无超时保护的全量并行回归：此前在测试结束后出现 `WorkflowLedgerClosedError` outbox 循环，须作为独立生命周期问题诊断，不能被本次契约修复掩盖。
