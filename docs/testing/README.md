# Testing 文档（现行参考）

**测试命令与矩阵的权威入口**是仓库根 [`tests/README.md`](../../tests/README.md)。
本目录只放**仍有运维价值**的补充说明；一次性报告已进 archive。

## 现行

| 文档 | 用途 |
| --- | --- |
| [remote-test-runner.md](remote-test-runner.md) | `scripts/remote_test_runner.py` 远程 Linux 测说明 |
| [electron-launcher-protocol-contract.md](electron-launcher-protocol-contract.md) | Launcher/Desktop Supervisor 协议形状（参考；实现以代码与 tests 为准） |

## 已归档

| 原文档 | 位置 |
| --- | --- |
| 2026-06-11 前端交互测试报告 | [`../archive/testing/`](../archive/testing/) |
| Electron 迁移 impact / window-provider ledger | [`../archive/testing/`](../archive/testing/) |

## 规则

- 新的「某日测试报告」默认写入 `docs/archive/testing/`，不堆在本目录。
- 协议变更先改测试与实现，再更新 `electron-launcher-protocol-contract.md` 摘要；不得以历史报告覆盖失败测试。
