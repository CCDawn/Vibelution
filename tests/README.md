# 测试脚本使用说明

> 本文档描述 Vibelution 项目测试脚本的结构、使用方法和规范。

---

## 一、测试目录结构

```
tests/
├── __init__.py                    # 测试包标识
├── conftest.py                    # pytest 配置和共享 fixtures
├── test_runner.py                 # 统一测试运行器（pytest 封装）
├── prompt_debugger.py             # 提示词打靶测试（工具变更时必用）
├── simulate_lifecycle.py          # 沙盘生命周期独立验证脚本
├── select_tests.py                 # 影响面测试选择器
├── test_matrix.yaml                # 变更范围到验证命令的映射
└── test_*.py                       # pytest 测试文件集合，按功能面持续增长
```

---

## 二、测试分组

### 2.1 按被测模块分组

| 测试文件 | 被测模块 | 分类 |
|---------|---------|------|
| `test_*tools*.py` / `test_tool_*.py` | tools 与 tool execution/registry/policy | tools / infrastructure |
| `test_web_*.py` / route-specific tests | FastAPI routes、Web services、前端契约相关后端面 | web |
| `test_runtime_*.py` / `test_launcher_*.py` | Launcher、runtime manager、进程生命周期 | runtime |
| `test_memory*.py` / `test_*knowledge*.py` / `test_rag_*.py` | Memory、Knowledge、RAG、ACL 与检索 | memory |
| `test_team_*.py` / `test_*workflow*.py` | Teams、Team workflow、source extraction、paper note | teams |
| `test_config_*.py` / `test_model_*.py` | 配置、模型发现、provider 能力与兼容性 | config |
| 其它 `test_*.py` | 按被测模块命名，优先靠 `tests/test_matrix.yaml` 和文件名定位 | module-specific |

---

## 三、使用方法

### 3.1 推荐验证顺序

日常开发优先从影响面选择器开始，不要默认直接跑整仓串行测试：

```bash
# 根据当前分支相对 main 的变更给出分层验证建议
python tests/select_tests.py --from-git main

# 只输出可复制执行的聚焦命令
python tests/select_tests.py --from-git main --commands-only
```

推荐顺序：

1. 先跑 selector 输出的 focused 命令。
2. 如果输出 `local-parallel`，再跑本地 `pytest-xdist` 的 `not serial` 并发层。
3. 如果输出 `local-serial`，必须在本机串行补跑对应 Launcher、端口、真实进程、Git、config 或共享 workspace 测试。
4. 如果输出 `remote-distributed`，可以用服务器/Docker 分片加速 Python `not serial` 回归，但它不是完整 gate。
5. 如果输出 `frontend`，必须单独跑对应 Vitest/build；Python 本地或远端测试都不能替代前端验证。

#### Provider-scoped LLM 配置收敛

配置 schema v2、Provider catalog/discovery、protocol、migration 与 Provider-first 前端变更使用以下聚焦命令：

```powershell
& 'C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe' -m pytest tests\test_llm_config_v2_integration.py tests\test_llm_config_schema_v2.py tests\test_model_config_migration.py -q
& 'C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe' -m pytest tests\test_provider_config_service.py tests\test_provider_discovery_adapters.py tests\test_model_config_migration.py tests\test_config_redaction.py -q
npm --prefix web test -- src/routes/configProviderLogic.test.ts src/routes/configRouteLogic.test.ts src/routes/ConfigRoute.layout.test.ts
npm --prefix web run build
```

这些自动化测试只使用 fixture 或临时目录；真实 operator config 的迁移、应用、回滚与 Launcher refresh 不属于自动化测试范围。

### 3.2 直接使用 pytest

```bash
# 广义串行全量，仅在发布前或定位复杂串行问题时使用
pytest tests/ -v

# 运行特定模块测试
pytest tests/test_memory.py -v

# 按关键字筛选
pytest tests/test_code_analysis_tools.py -v -k "diff"

# 查看当前 pytest 文件数量
python -c "from pathlib import Path; print(len(list(Path('tests').glob('test_*.py'))))"

# 遇错即停
pytest tests/ -v -x
```

### 3.3 使用 test_runner.py

```bash
# 批量串行运行完整测试（简洁模式）
python tests/test_runner.py

# 详细输出
python tests/test_runner.py --verbose

# 跳过慢速测试
python tests/test_runner.py --fast

# 只使用进程级并行执行可并行测试文件（排除 serial）
python tests/test_runner.py --parallel --workers 4

# 完整混合验证：not serial 并行 + serial 串行兜底
python tests/test_runner.py --hybrid --workers 4

# 快速并行：跳过 slow 和 serial 标记
python tests/test_runner.py --fast --parallel --workers 4

# 逐文件诊断：只在需要定位失败文件时使用
python tests/test_runner.py --per-file
```

`test_runner.py` 面向健康审计，会在构造 pytest 命令时显式覆盖项目默认的遇错即停设置，尽量收集同一批次里的多个失败；需要快速停在首个失败时，直接使用 `pytest ... -x`。

### 3.4 进程级并行策略

Vibelution 支持通过 `pytest-xdist` 做进程级并行，但默认测试命令仍保持串行，避免全局状态、真实工作区、端口和后台进程类测试被误并发执行。

推荐入口：

```bash
# 直接使用 pytest-xdist
pytest tests/ -n 4 --dist loadfile -m "not serial"

# 使用项目 test runner
python tests/test_runner.py --parallel --workers 4

# 使用项目 test runner 做完整混合验证
python tests/test_runner.py --hybrid --workers 4
```

并行策略：

- 优先使用 `--dist loadfile`，按测试文件分发，降低同一文件内共享 fixture/全局状态的交叉风险。
- 在并行模式下排除 `serial` 标记；涉及真实进程、端口、共享全局状态、真实 workspace、外部 config 或 Launcher/runtime 生命周期的测试应标记为 `serial`。
- 需要完整验证时优先使用 `--hybrid`：先并行运行 `not serial`，再串行运行 `serial`，避免把并行子集误判为全量通过。
- 不把 `-n auto` 作为默认；本地开发建议先用 `--workers 2` 或 `--workers 4`，再根据耗时和稳定性调整。
- 广义全量回归仍应保留串行兜底；并行适合日常快速反馈和已标注边界的稳定子集。

### 3.5 使用影响面测试选择器

`tests/test_matrix.yaml` 记录高频改动范围到验证命令的映射，`tests/select_tests.py` 根据变更文件输出建议测试命令。它只做选择和解释，不自动执行命令，也不改变默认 pytest 串行策略。

```bash
# 手动输入变更文件并查看结构化结果
python tests/select_tests.py --changed-file core/web/services/session_service.py --json

# 从 git diff 读取变更文件
python tests/select_tests.py --from-git HEAD~1

# 只输出命令，便于复制到当前 worktree 执行
python tests/select_tests.py --from-git main --commands-only
```

使用原则：

- 先运行 selector 给出的聚焦命令，再按风险扩大到相关文件或全量回归。
- `validationLayers` 是验证边界提示：`local-parallel` 可并发，`local-serial` 必须本地串行，`remote-distributed` 只是服务器加速，`frontend` 必须单独跑前端测试或构建。
- selector 输出的是建议，不替代工程判断；涉及 Launcher、真实进程、外部 config、Git 副作用或共享 workspace 的测试仍按 `serial` 边界处理。
- 没有规则命中时，默认输出轻量 runner smoke、collect-only 和 `git diff --check`，帮助 Agent 先判断测试集合是否可收集。
- 新增高频模块或拆分测试文件后，同步补充 `tests/test_matrix.yaml` 和 `tests/test_select_tests.py`。

### 3.6 本地质量门

`scripts/local_quality_gate.py` 有三个 mode，按任务阶段选择：

- `commit`：由 pre-commit hook 自动调用，以 staged paths 驱动；diff check 与 Python Ruff 使用 Git index 中的 staged 内容。gate-definition 文件同时存在 staged 与 unstaged 内容时拒绝提交；gate-definition staged 时还会在当前 worktree 运行 focused self-test，因此未 stage 的测试或 `conftest.py` 可能影响结果。
- `closeout --base main --claim-id <claim-id>`：只在内容已提交且 clean 的 task worktree 运行，绑定 claim、本地 `main` SHA、HEAD SHA、selector 命令和 merge preflight，并写入 `.runtime/quality_gates/<task-id>.json`。
- `verify-manifest --manifest <path> --base main`：在进入 root local `main` fast-forward gate 前复核 manifest 的 schema、outcome、branch/worktree、main/HEAD/changed files、active claim、clean 状态、checks、allowlisted command 结果与 fast-forward ancestry。`passed` 是当前授权证据，不表示已经 merge。

首次配置 hook 使用 `git config core.hooksPath .githooks`。`powershell -ExecutionPolicy Bypass -File scripts/doctor.ps1 -Json` 只读报告 `checks.git_hooks_path` 及固定修复命令，不会静默写 Git 配置。远端 CI 的 `workflow_dispatch` 可按需补充验证，但 remote push 不是默认本地闭环的一部分。

Outcome 必须结合 mode 解释，每个组合只对应一个恢复动作：

| Mode | Outcome | 操作 |
| --- | --- | --- |
| `commit` | `passed` | 当前 commit 轻门通过，可继续 commit；该 mode 不生成 manifest |
| `commit` | `failed` | 修复 staged diff、staged Python Ruff 或 gate focused self-test 的首个失败后重试 commit |
| `commit` | `gate_definition_dirty` | 整文件 stage gate-definition 或拆成独立 commit，再重试 commit |
| `closeout` | `passed` | 复核生成的 manifest 后进入本地 main fast-forward gate |
| `closeout` | `failed` | 先按当前 branch 修复非法 task branch/precondition；若已有失败命令，则按首个失败命令及其 `failureSummary` 修复后重跑 closeout |
| `closeout` | `stale_main` | 在任务 worktree 合并最新本地 main，解决冲突并重跑 closeout |
| `closeout` | `claim_conflict` | 修正或续期本任务 claim，不使用其他任务 claim，然后重跑 closeout |
| `closeout` | `dirty_worktree` | 提交或撤回本任务未提交内容，使 task worktree clean 后重跑 closeout |
| `closeout` | `merge_conflict` | 仅在任务 worktree 解决冲突并重跑 closeout |
| `closeout` | `unsupported_validation_command` | 修正 matrix 为允许命令族，不放宽到 shell，然后重跑 closeout |
| `verify-manifest` | `passed` | manifest 与当前 task branch/worktree/HEAD/changed files 一致，main 仍新鲜且是 task HEAD 祖先，claim、clean 状态、checks 与 commands 仍有效，可进入 merge gate |
| `verify-manifest` | `failed` | manifest 不可读，或 schema/`outcome`/branch/worktree/HEAD/changed files/checks/commands 被篡改或不匹配；生成或选择正确 manifest，必要时重跑 closeout |
| `verify-manifest` | `stale_main` | 当前本地 main 已变化或不再是 task HEAD 祖先；回任务 worktree 同步最新 main，并重跑 closeout 生成新 manifest |
| `verify-manifest` | `claim_conflict` | manifest claim 已失效、缺失或不覆盖当前 changed files；修正或续期本任务 claim 后重跑 closeout |
| `verify-manifest` | `dirty_worktree` | task worktree 在 closeout 后出现改动；提交或撤回本任务内容，使 worktree clean 后重跑 closeout |

质量门只生成或复核证据，不执行 merge、claim release、junction/worktree/branch 删除。冲突和 `stale_main` 都回 task worktree 处理；root local `main` 仅在 clean 且 SHA 仍匹配时执行 `git merge --ff-only <task-branch>`，随后做最小 post-merge verification，并只清理本任务资源。

### 3.7 使用服务器分布式测试

服务器分布式用于高吞吐 Python 回归：

```bash
python scripts/remote_test_runner.py --backend docker --distributed
```

边界：

- 只覆盖 Python pytest 的 `not serial` 子集。
- 模块级 `serial` 测试文件不会进入分布式目标清单。
- 不覆盖前端 Vitest、前端 build、Launcher/runtime 本地生命周期、Windows-only、真实端口/进程、operator config、Git 副作用测试。
- 远端失败时先看 `logs/remote_test_runs/<run-id>/remote-test.log` 和本地 `local-test.log`，定位首个失败分片后再聚焦复跑。

### 3.8 使用 prompt_debugger.py（工具变更时必用）

验证模型能够正确理解并调用工具。**每次添加或修改工具后必须运行**。

```bash
# 测试指定工具（如 shell_tools, memory_tools, search_tools）
python tests/prompt_debugger.py --tool shell_tools

# 运行内置测试用例集
python tests/prompt_debugger.py --suite

# 交互模式
python tests/prompt_debugger.py "你的测试 prompt"
```

验证标准：
- 模型能识别工具名称和用途
- 模型能正确解析工具参数
- 模型在适当场景下主动调用该工具
- 无幻觉调用（不该调用时不调用）

### 3.9 独立脚本 simulate_lifecycle.py

不调用大模型，验证生命周期防断裂加固：

```bash
python tests/simulate_lifecycle.py
```

测试内容：
1. CLI 命令错误检测
2. 记忆保存功能
3. 重启前强制快照
4. 数据库写入
5. workspace 结构完整性

---

## 四、测试规范

### 4.1 命名规范

- 测试文件：`test_<模块名>.py`
- 测试类：`Test<模块名>`
- 测试方法：`test_<功能名>`

### 4.2 conftest.py 共享 fixtures

```python
@pytest.fixture
def project_root():
    """项目根目录"""
    return Path(__file__).parent.parent

@pytest.fixture
def workspace_dir(project_root):
    """工作区目录"""
    return project_root / "workspace"

@pytest.fixture
def mock_llm():
    """Mock LLM 响应"""
    ...

@pytest.fixture
def test_config():
    """测试配置"""
    ...
```

### 4.3 添加新测试

1. 在 `tests/` 目录创建 `test_<模块名>.py`
2. 使用 pytest 风格编写测试
3. 导入被测模块
4. 运行 `pytest tests/test_<模块名>.py -v` 验证

---

## 五、测试框架组件

| 组件 | 职责 | 调用场景 |
|------|------|---------|
| `prompt_debugger.py` | 提示词打靶测试：验证模型对工具的理解和调用 | **添加/修改工具时必用** |
| `test_runner.py` | 单元/集成测试运行器：验证代码正确性 | 日常开发、提交前 |
| `simulate_lifecycle.py` | 生命周期验证：不调用大模型，验证防断裂机制 | 重启前必检 |
| `conftest.py` | pytest 配置：单例重置、隔离工作空间、共享 fixtures | pytest 自动加载 |
| `test_*.py` | pytest 测试文件集合：覆盖核心、工具、Web、进化、运行时和配置等模块 | 日常开发、CI |

---

## 六、测试覆盖率目标

| 模块 | 目标覆盖率 |
|------|-----------|
| core/infrastructure/ | ≥80% |
| core/orchestration/ | ≥80% |
| core/prompt_manager/ | ≥80% |
| core/restarter_manager/ | ≥80% |
| tools/ | ≥80% |
