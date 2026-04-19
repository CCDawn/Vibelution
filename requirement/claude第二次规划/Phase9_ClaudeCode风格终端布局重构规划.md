# Phase 9: Claude Code 风格终端布局重构

**版本：** v1.0
**日期：** 2026-04-19
**状态：** ✅ 完成

---

## 1. 需求分析

**目标：** 将当前终端改造成 Claude Code 风格布局

**用户原始需求：**
- `terminals/5.txt` 第 722-734 行展示了当前的 Baby Claw 状态输出
- 用户希望这部分始终保持在最前方
- Log 输出保持在下方
- 整体类似 Claude Code CLI 的界面风格

**Claude Code CLI 布局分析：**
```
┌─────────────────────────────────────────────┐
│ [状态栏: 模型 | 项目 | Git分支 | 状态]        │  ← 固定顶部
├─────────────────────────────────────────────┤
│                                             │
│          [可滚动内容区]                       │  ← 中间滚动
│          工具执行结果、思考过程               │
│          LLM 响应等                          │
│                                             │
├─────────────────────────────────────────────┤
│ [日志区: 最近日志条目]                        │  ← 固定底部
└─────────────────────────────────────────────┘
```

**当前实现问题：**
- `UIManager` 使用 Rich `Live` 刷新机制
- 状态面板和日志面板在同一布局中
- 没有明确的"固定顶部"和"固定底部"区域划分
- 工具输出直接打印，破坏 Live 刷新

**涉及模块：** `core/ui/cli_ui.py`

**变更范围：** 修改/重构 `UIManager` 类

---

## 2. 设计

**方案：**

### 核心数据结构

```python
class TerminalLayout:
    """终端布局管理器 - Claude Code 风格"""

    def __init__(self, console: Console):
        self.console = console
        self._header_height = 8      # 顶部状态栏高度
        self._footer_height = 5      # 底部日志栏高度
        self._content_lines = []     # 中间可滚动内容
        self._max_content = 100     # 最大保留行数

    def _render(self) -> Table:
        """构建完整布局"""
        # 1. 顶部状态栏 (固定)
        header = self._create_header_panel()

        # 2. 中间可滚动内容区
        content = self._create_content_area()

        # 3. 底部日志栏 (固定)
        footer = self._create_log_panel()

        # 组装: header | content | footer (垂直堆叠)
        layout = Table(box=None, show_header=False)
        layout.add_column(justify="left")
        layout.add_row(header)
        layout.add_row(content)  # 这个区域会随着内容增加而扩展
        layout.add_row(footer)

        return layout
```

### 关键设计决策

| 决策点 | 方案A | 方案B | 选择 | 原因 |
|--------|-------|-------|------|------|
| 布局实现 | Rich `Live` + 垂直布局 | 纯手动控制台定位 | A | `Live` 支持原地刷新，性能更好 |
| 内容区滚动 | 记录所有行，手动截断 | Rich `ScrollablePane` | A | 更简单可靠，避免复杂滚动逻辑 |
| 工具输出 | 捕获并添加到内容区 | 直接打印后刷新 | A | 保持 Live 刷新一致性 |
| 日志固定 | 底部固定行数 | 全部显示 | B | 空间有限，固定 5-8 行足够 |

### 布局结构

```
┌──────────────────────────────────────────────────────────────┐
│  Baby Claw v1.0    Lv.1 (0岁)   😊100 🍖100 ⚡100           │  ← 顶部: 8行
│  ❤️100 💗50  ⭐经验 [████░░] 50/100                         │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  🔧 get_code_entity_tool(file_path=agent.py, ...)           │  ← 中间: 可滚动
│     ✅ get_code_entity_tool                                 │
│     [AST] 实体: think_and_act                                │
│                                                              │
│  🔧 cli_tool(command=Get-ChildItem tests -Name)             │
│     ✅ cli_tool                                              │
│     backups, __pycache__, ...                               │
│                                                              │
├──────────────────────────────────────────────────────────────┤
│  📝 00:27:20 INFO [PromptManager] 加载 AGENTS.md            │  ← 底部: 5行
│  📝 00:27:21 INFO [PromptManager] 加载 SOUL.md               │
└──────────────────────────────────────────────────────────────┘
```

### 核心方法

```python
class UIManager:
    # ... 现有属性 ...

    def _create_header_panel(self) -> Panel:
        """创建顶部状态面板 - 8行"""
        # 包含: ASCII Art + 状态信息 + 属性条

    def _create_content_area(self) -> Panel:
        """创建中间内容区 - 可滚动"""
        if not self._content_lines:
            return Panel("[dim]等待任务...[/dim]", box=None)
        return Panel(
            "\n".join(self._content_lines[-self._max_content:]),
            box=None,
            padding=0,
        )

    def _create_log_panel(self) -> Panel:
        """创建底部日志面板 - 5行"""
        recent = self._logs[-5:] if len(self._logs) > 5 else self._logs
        return Panel(
            "\n".join(recent),
            title=f"[bold green]📝 日志 ({len(self._logs)})[/]",
            border_style="green",
            height=self._footer_height,
        )

    # ========== 内容区操作 ==========

    def add_content(self, text: str):
        """添加内容到中间可滚动区"""
        self._content_lines.append(text)
        if len(self._content_lines) > self._max_content:
            self._content_lines.pop(0)
        self.refresh()

    def add_content_block(self, lines: List[str]):
        """添加多行内容块"""
        for line in lines:
            self.add_content(line)

    # ========== 工具输出 (捕获到内容区) ==========

    def print_tool_start(self, tool_name: str, args: Dict = None):
        """打印工具开始 - 输出到内容区"""
        self.increment_tool_count()
        tool_icon = self.theme.get_tool_icon(tool_name)
        args_str = ""
        if args:
            args_str = ", ".join([f"{k}={str(v)[:30]}" for k, v in args.items()][:3])
        self.add_content(f"[bold magenta]{tool_icon} {tool_name}[/bold magenta]" +
                         (f"({args_str})" if args_str else ""))

    def print_tool_result(self, tool_name: str, result: str, success: bool = True):
        """打印工具结果 - 输出到内容区"""
        icon = "✅" if success else "❌"
        color = "green" if success else "red"
        preview = result[:300] + "..." if len(result) > 300 else result
        self.add_content(f"  {icon} [{color}]{tool_name}[/{color}]")
        if preview:
            self.add_content(f"     {preview}")
```

### 决策记录

| 决策点 | 方案A | 方案B | 选择 | 原因 |
|--------|-------|-------|------|------|
| 工具输出目标 | 内容区 | 直接打印 | A | 保持 Live 刷新一致性，工具输出不会破坏布局 |
| 日志行数 | 固定5行 | 固定8行 | A | 空间效率与信息量平衡 |
| 内容区截断 | 超过100行删除旧行 | 保留所有但限制渲染 | A | 内存保护 |

---

## 3. 实现

**修改文件：**

| 文件路径 | 修改内容 | 变更类型 |
|----------|----------|----------|
| `core/ui/cli_ui.py` | 重构 `UIManager` 类，增加三段式布局 | 修改 |
| `agent.py` | 集成 Live 显示，修改输出流程 | 修改 |

**实现状态：**

| 交付物 | 状态 | 完成标准 |
|--------|------|----------|
| `TerminalLayout` 布局类 | ✅ 完整 | 三段式布局正确渲染 |
| `_create_header()` | ✅ 完整 | 顶部状态栏（完整宽度） |
| `_create_content_area()` | ✅ 完整 | 可滚动内容区 |
| `_create_log_panel()` | ✅ 完整 | 6行底部日志栏 |
| `add_content()` | ✅ 完整 | 内容添加方法 |
| `print_tool_start/result()` | ✅ 完整 | 输出到内容区（非直接打印） |
| `agent.py` 集成 | ✅ 完整 | Live 显示正确启动/停止 |

**实际布局输出：**
```
+-------------------------------- 🦞 虾宝状态 --------------------------------+
| (\ /)  Lv.1 (0岁)                                                           |
|   ( ^.^)  🦞 IDLE  TURN #0                                                  |
|    >^<  😊心情: 100/100  🍖饱食: 100/100  ⚡活力: 100/100                   |
|   /| |\  ❤️健康: 100/100  💗爱心: 50/100  ⭐经验 [░░░░░] 0/100              |
|   (_|_)                                                                     |
+-----------------------------------------------------------------------------+
+---------------------------- 📤 内容输出 (N 条) -----------------------------+
|  [可滚动内容]                                                               |
+-----------------------------------------------------------------------------+
+-------------------------------- 📝 日志 (N) --------------------------------+
|  14:39:30 💬 SYS 系统时间: 2026-04-19 14:39:30                              |
+-----------------------------------------------------------------------------+
```

---

## 4. 测试

**测试方法：**
```bash
cd C:\Users\17533\Desktop\self-evo-baby
python agent.py --auto
```

**验证点：**
1. ✅ 顶部状态栏固定显示 Baby Claw 状态
2. ✅ 底部日志栏固定显示最近日志
3. ✅ 中间内容区可滚动显示工具执行结果
4. ✅ 布局不因内容增加而崩溃
5. ✅ Ctrl+C 可正常中断

---

## 5. 文档归档

**规划文档：** `requirement/claude第二次规划/Phase9_ClaudeCode风格终端布局重构规划.md`

---

## 6. Git 提交

```markdown
## Phase 9 (2026-04-19)

### 重构
- `core/ui/cli_ui.py`: Claude Code 风格三段式终端布局
  - 顶部固定状态栏 (Baby Claw 状态)
  - 中间可滚动内容区 (工具输出、思考过程)
  - 底部固定日志栏 (最近5条日志)
```
