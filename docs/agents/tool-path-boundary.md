# Agent 文件工具路径边界

**用途：** 说明 Agent 文件工具（`read_file` / `list_file` / `create_file` / `edit_file`，经
`Key_Tools` 的 `read_file_tool` / `write_file_tool` 暴露）能读写到哪里，以及如何显式放宽。
**代码权威：** [`tools/shell_tools.py`](../../tools/shell_tools.py)
（`_tool_path_roots` / `_path_boundary_message` / `_is_path_allowed`）。

---

## 允许根（唯一权威判定）

路径按 `Path.resolve()` 解析后，必须落在下面任一根据内：

| 根 | 说明 |
| --- | --- |
| 项目 checkout | `tools/shell_tools.PROJECT_ROOT` |
| 当前 workspace | `_get_workspace_root()`（含 workspace override，即实例 workspace） |
| 本项目运行态存储 | 本 checkout 的 `workspace` / `data` / `runtime` / `logs` / `memory` / `cache` |
| 临时根 | 系统 temp，以及测试运行器声明的 `PYTEST_DEBUG_TEMPROOT` |
| operator 显式配置 | `config` 的 `security.allowed_directories` |

判定只看**解析后**的路径，所以 `..`、大小写、软链都不是绕过手段。

## 刻意不使用的两个来源

- `tools.allowed_directories`：其默认值包含整个用户主目录（`Path.home()`）与 `Path.cwd()`，
  拿它做工具边界等于放行主目录下的凭据目录。边界只认 operator 显式填写的
  `security.allowed_directories`（默认空）。
- `PathSandbox`（`core/infrastructure/security.py`）：它只认项目根，而文件工具的合法写入目标
  （实例 workspace、运行态存储）本就在项目根之外，历史上它靠“绝对路径一律放行”才没拦住正常写入。
  边界规则现在只有一个来源，不再保留这条自相矛盾的规则。

## 放宽方式（二选一，都需显式）

1. `security.allowed_directories` 追加目录 —— 面向该部署长期生效；
2. Agent 的沙箱模式设为 `danger_full_access` —— 该回合全量放行，用于受控实验。

## 失败时的行为

越界不会静默降级：`read_file` / `list_file` / `create_file` / `edit_file` 返回带
`[SECURITY]` 的可操作错误，列出当前允许根并说明上面两种放宽方式。

## 回归守卫

`tests/test_shell_tool_path_boundary.py` 固定这些语义：越界读写必须被拒、临时根与项目内相对写仍可用、
主目录默认不是允许根、`security.allowed_directories` 与 `danger_full_access` 能放宽。
