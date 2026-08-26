# 测试选择器 Python 导入测试前沿修复

> Status: Implemented
> Date: 2026-08-26
> Scope: `tests/select_tests.py` 的未映射 Python 产品代码 fallback，以及其契约测试与使用说明。

## 目标

把 fallback 从“测试直接 import 被改模块”扩展为“从被改模块沿反向产品依赖，选择最先被测试直接 import 的模块”。矩阵规则仍优先；每条路径在首次命中测试时停止，既不把轻量 smoke 当覆盖，也不扩张为完整反向闭包。

## 研究与裁决

- 本地复用：`tests/select_tests.py` 已用标准库 `ast` 解析测试 import，并按 serial marker 分开命令；`core/code_context_graph/service.py` 的图是运行时/可视化数据模型，不适合塞进命令行 selector。
- Python 官方 AST 文档确认 `ast.parse`、`Import` 与 `ImportFrom(module, names, level)` 足以无执行地提取绝对和相对 import。
- [grimp](https://github.com/python-grimp/grimp)（BSD-2-Clause，固定至 `f4d9ecfc9495bd1419623f15124c5b9a63de1048`）验证了“反向可达模块”模型；不引入其 Rust 扩展，只借图方向和闭包查询语义。
- `pytest-testmon`（MIT）依赖 coverage 数据库和持续基线，适合动态依赖选择；本仓的 selector 必须在新环境、未跑过完整测试时仍能工作，因此不采用。

## 实施路径

1. 枚举 `PYTHON_PRODUCT_ROOTS` 内可导入模块，解析全部静态 import，支持 `from .`、`from ..` 和 `from package import child` 的已知子模块写法。
2. 将 import 边反向，针对每个未映射变更模块做 BFS/visited；每个节点先查测试直接 import，命中后收集测试并停止该路径，保留现有 parallel/serial 拆分和命令去重。
3. 保持 matrix 对已知高风险面拥有优先权；动态 import、语法损坏或无静态测试 import 继续作为 coverage gap 报告。首版每次运行重建小图，不写磁盘缓存，避免脏工作区或 mtime 失效导致假绿。
4. 用合成两跳链、相对 import 链和当前 `core/pet_system/utils/storage.py` 路径验证；同时保留直接 import、串行分流和 orphan gap 回归。

## 成功证据

- 改动底层模块会选择最近直接 import 上层模块的测试，而不会继续扩张到该边界以外。
- 相对 import 不会漏边；循环依赖不会无限遍历。
- `core/pet_system/utils/storage.py` 不再只得到 coverage gap，稳定选择 4 个 Pet 边界测试。
- selector 契约测试、实际 selected pytest 命令和任务 closeout 均通过。

## 边界与后续

- 不把动态 import、运行时插件装配或测试执行覆盖率伪装成静态依赖；这些仍应由矩阵/coverage gap 显式处理。
- 不在本轮实现跨进程或跨 HEAD 的 selector 缓存；只有实际图构建成为可测瓶颈时，才另行设计带环境与文件指纹的缓存。
