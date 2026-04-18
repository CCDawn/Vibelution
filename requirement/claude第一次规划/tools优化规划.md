# 工具优化规划文档

**日期：** 2026-04-17
**版本：** v1.0
**目标：** 优化工具系统，提升 MiniMax 2.7 兼容性

---

## 一、问题分析总结

基于探索报告，主要问题如下：

### 1.1 MiniMax 2.7 兼容性问题

| 问题 | 严重程度 | 影响工具 |
|------|----------|----------|
| `arguments` 可能返回 JSON 字符串而非 dict | 🔴 高 | 所有工具 |
| 工具参数缺少默认值 | 🔴 高 | cli_tool |
| 工具返回格式不统一 | 🟡 中 | 所有工具 |
| 错误消息格式不一致 | 🟡 中 | 所有工具 |

### 1.2 已修复问题

1. ✅ `cli_tool` command 参数已有默认值 `""`
2. ✅ `_execute_tool` 已添加 JSON 字符串解析逻辑
3. ✅ `_convert_tool` 已添加 schema.model_fields 类型检查

### 1.3 仍需优化的问题

| 优先级 | 问题 | 解决方案 |
|--------|------|----------|
| P0 | MiniMax 返回 `arguments` 为 JSON 字符串 | 已在 `_execute_tool` 修复 |
| P1 | 工具参数默认值不一致 | 统一所有工具参数默认值 |
| P1 | 错误消息格式不统一 | 标准化错误格式 |
| P2 | 输出长度控制不完善 | 添加 `max_output_chars` 参数 |

---

## 二、优化实施计划

### Phase 1: 工具参数标准化 ✅ (已完成部分)

**目标：** 确保所有工具函数都有合理的默认值

#### 已完成
- ✅ `cli_tool(command: str = "")` - 已修复

#### 待修复
- [ ] `grep_search_tool(regex_pattern: str, ...)` - `regex_pattern` 需要默认值
- [ ] `list_directory(path: str = ".")` - 已有默认值，需验证
- [ ] 其他工具参数检查

### Phase 2: 错误处理标准化

**目标：** 统一所有工具的错误消息格式

```
状态: [success|error] | 消息: ...
```

### Phase 3: 输出长度控制

**目标：** 防止工具输出过长导致上下文爆炸

- 添加 `max_output_chars` 参数到所有可能返回大量内容的工具
- 默认限制: 8000 字符
- 超过时截断并提示

### Phase 4: MiniMax 2.7 兼容性验证

**目标：** 确保工具与 MiniMax 2.7 API 完全兼容

1. 验证 `tool_args` 正确解析
2. 验证工具名称映射
3. 验证返回值格式

---

## 三、具体优化任务

### 任务 1: grep_search_tool 参数默认值

**文件:** `tools/search_tools.py`
**问题:** `regex_pattern` 是必需参数，无默认值
**修复:**
```python
def grep_search_tool(
    regex_pattern: str = "",  # 添加默认值
    include_ext: str = ".py",
    search_dir: str = ".",
    case_sensitive: bool = True,
    max_results: int = None
) -> str:
    if not regex_pattern:
        return '{"status": "error", "message": "正则表达式不能为空"}'
```

### 任务 2: Key_Tools.py 中的 grep_search_tool 包装器

**文件:** `tools/Key_Tools.py`
**问题:** 包装器没有默认值，直接传递参数
**修复:** 同步更新包装器

### 任务 3: 输出格式标准化

**目标:** 返回 JSON 格式，便于解析

```python
# 标准成功响应
{"status": "success", "data": {...}}

# 标准错误响应
{"status": "error", "code": "ERROR_CODE", "message": "错误描述"}
```

---

## 四、测试验证

### 测试用例

1. ✅ cli_tool 无参数调用
2. ✅ grep_search_tool 无参数调用
3. ✅ list_directory 默认参数
4. ✅ execute_shell_command 超时处理
5. ✅ MiniMax JSON 字符串参数解析

### 验证命令

```bash
# 运行工具测试
pytest tests/test_shell_tools.py -v
pytest tests/test_search_tools.py -v

# 运行关键修复验证
python -c "from tools import cli_tool; print(cli_tool(command=''))"
```

---

## 五、实施时间线

| 阶段 | 任务 | 预计时间 |
|------|------|----------|
| Phase 1 | 参数标准化 | 30 分钟 |
| Phase 2 | 错误格式标准化 | 30 分钟 |
| Phase 3 | 输出长度控制 | 30 分钟 |
| Phase 4 | 兼容性验证 | 30 分钟 |

---

## 六、风险管理

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 修改影响现有功能 | 高 | 先备份，运行完整测试 |
| JSON 输出破坏现有流程 | 中 | 添加 `format=json` 参数可选 |
| 性能下降 | 低 | 确保截断逻辑高效 |

---

## 七、交付物

1. ✅ 优化后的 `tools/shell_tools.py`
2. ✅ 优化后的 `tools/search_tools.py`
3. ✅ 优化后的 `tools/Key_Tools.py`
4. ✅ 更新的 `workspace/prompts/` 相关提示词
5. ✅ 任务完成报告
