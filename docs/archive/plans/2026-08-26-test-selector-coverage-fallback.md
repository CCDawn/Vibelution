# 测试选择器 Python 覆盖回退修复计划

## 目标

让没有命中 `tests/test_matrix.yaml` 专项规则的 Python 产品改动，仍能得到与其静态导入关系匹配的聚焦 pytest 命令；若无法可靠推导，必须明确报告缺口，不能把无关的 runner smoke 表示成产品验证。

## 证据与裁决

- 现有矩阵只对约 46.8% 的 Python 产品文件提供专项映射；`core/agent_kernel/adapters.py`、`core/chat/conversation_ledger.py` 等会退化成 `tests/test_runner.py`。
- 仓内测试已经以标准 `import` / `from ... import ...` 方式引用源码；AST 可在无新依赖、无执行被测代码的前提下建立反向索引。
- `pytest-testmon`（MIT）依赖 runtime coverage 数据库和基线运行，适合长期动态影响分析，但不适合当前可复制 selector 命令的零状态工作流。因此只借鉴其“不要静默遗漏变更”的原则，不引入插件或状态文件。

## 推荐实现

1. 保持 YAML 专项规则优先，并只对未被任何专项规则命中的 Python 产品文件启用回退。
2. 使用 `ast` 读取 `tests/test_*.py` 的静态 `import` 与 `from ... import`，按源码模块名反查直接引用它的测试文件。
3. 为命中的文件输出 `python-import-fallback` 规则和显式 pytest 命令；多个测试文件沿用现有 xdist `loadfile` 改写。
4. 对改动的 `tests/test_*.py`，输出该测试文件本身；不能静态解析或找不到关联测试的产品文件写入结构化 `coverageGaps` 和人类可读提示，不追加伪覆盖命令。
5. 新增回归测试，覆盖：直接导入、`from` 导入、矩阵优先、已改测试文件、无法关联时的显式缺口，以及 CLI JSON 文本。

## 保护边界与验证

- 不修改产品源码、测试矩阵专项规则或 closeout 执行语义。
- 不尝试根据字符串、动态 import、运行时 monkeypatch 或间接调用猜测依赖关系；这类情况属于可见的覆盖缺口，后续以专项规则补齐。
- 运行 `tests/test_select_tests.py`，再用真实代表文件检查 selector 命令，并运行该命令确认生成的 pytest 参数可执行。
