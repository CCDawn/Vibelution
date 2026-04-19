#!/usr/bin/env python3
"""
记忆与任务管理模块 - 跨生命周期状态管理

整合了记忆管理和任务管理功能：

【记忆管理】
- 世代索引 (memory.json) - 保留当前世代号、核心智慧摘要、当前目标
- 世代档案 (archives/gen_{N}_history.json) - 完整保留每一世代的对话记录和思考过程

【任务管理】
- set_plan / tick_subtask - 任务清单驱动执行
- 重启前强制检查任务完成度

设计原则：详细档案只在 Agent 主动读取时才加载，不增加常规运行的 Token 负担。
"""

import json
import os
import re
from datetime import datetime
from typing import Optional, List, Dict, Any

# 导入统一工作区管理器
from core.infrastructure.workspace_manager import get_workspace
from core.capabilities.task_manager import get_task_manager


# ============================================================================
# 记忆管理工具
# ============================================================================

def _get_memory_index_path() -> str:
    """获取记忆索引文件路径"""
    ws = get_workspace()
    return str(ws.memory_index)


def _get_archives_path() -> str:
    """获取档案库路径"""
    ws = get_workspace()
    archives = ws.archives_dir
    archives.mkdir(parents=True, exist_ok=True)
    return str(archives)


def _get_dynamic_prompt_path() -> str:
    """获取动态提示词文件路径"""
    ws = get_workspace()
    return str(ws.get_prompt_path("DYNAMIC.md"))


def _get_default_memory() -> dict:
    """获取默认的记忆结构"""
    return {
        "current_generation": 1,
        "core_wisdom": "初始状态",
        "current_goal": "熟悉环境",
        "total_generations": 1,
        "last_archive_time": None,
    }


def _load_memory() -> dict:
    """从文件加载记忆，文件不存在则初始化"""
    memory_file = _get_memory_index_path()
    if not os.path.exists(memory_file):
        memory = _get_default_memory()
        _save_memory(memory)
        return memory

    try:
        with open(memory_file, 'r', encoding='utf-8') as f:
            memory = json.load(f)

        # 迁移旧结构到新结构
        needs_migration = False
        if "generation" in memory and "current_generation" not in memory:
            memory["current_generation"] = memory.pop("generation")
            needs_migration = True
        if "core_context" in memory and "core_wisdom" not in memory:
            memory["core_wisdom"] = memory.pop("core_context")
            needs_migration = True
        if "total_generations" not in memory:
            memory["total_generations"] = memory.get("current_generation", 1)
            needs_migration = True

        if needs_migration:
            _save_memory(memory)

        return memory
    except (json.JSONDecodeError, IOError):
        memory = _get_default_memory()
        _save_memory(memory)
        return memory


def _save_memory(memory: dict) -> bool:
    """保存记忆到文件"""
    from core.logging import debug_logger

    memory_file = _get_memory_index_path()
    try:
        with open(memory_file, 'w', encoding='utf-8') as f:
            json.dump(memory, f, ensure_ascii=False, indent=2)
        debug_logger.info(f"[记忆保存] 成功: {memory_file}")
        return True
    except IOError as e:
        debug_logger.error(f"[ERROR] 记忆保存失败 (IOError): {e}")
        return False
    except TypeError as e:
        debug_logger.error(f"[ERROR] 记忆保存失败 (序列化错误): {e}")
        return False
    except Exception as e:
        debug_logger.error(f"[ERROR] 记忆保存失败 (未知错误): {e}")
        return False


def read_memory_tool() -> str:
    """
    读取当前的世代索引（轻量级，不加载详细档案）。
    
    Returns:
        JSON字符串，包含:
        - current_generation: 当前世代
        - core_wisdom: 核心智慧摘要
        - current_goal: 本世代核心目标
        - total_generations: 总世代数
    """
    memory = _load_memory()
    return json.dumps(memory, ensure_ascii=False, indent=2)


def get_memory_summary_tool() -> str:
    """
    获取人类可读的记忆摘要，用于注入到Prompt中。
    
    Returns:
        格式化的记忆字符串
    """
    memory = _load_memory()
    current_gen = memory.get('current_generation', 1)
    total_gens = memory.get('total_generations', 1)
    core_wisdom = memory.get('core_wisdom', '无')
    current_goal = memory.get('current_goal', '待定')
    
    lines = [
        f"【当前世代】: G{current_gen} (共 {total_gens} 代)",
        f"【核心智慧】: {core_wisdom}",
        f"【本世代目标】: {current_goal}",
        f"【档案库】: memory/archives/ (可按需读取)",
    ]
    return "\n".join(lines)


def get_generation_tool() -> int:
    """获取当前世代数"""
    return _load_memory().get("current_generation", 1)


def get_current_goal_tool() -> str:
    """获取当前目标"""
    return _load_memory().get("current_goal", "")


def get_core_context_tool() -> str:
    """获取核心上下文"""
    return _load_memory().get("core_wisdom", "")


# 向后兼容别名 (agent.py 等旧代码使用这些无后缀名称)
get_current_goal = get_current_goal_tool
get_core_context = get_core_context_tool


def archive_generation_history(
    generation: int,
    history_data: List[Dict[str, Any]],
    core_wisdom: str,
    next_goal: str,
) -> str:
    """
    将当前世代的完整历史记录归档到磁盘。
    
    Args:
        generation: 当前世代编号
        history_data: 包含本轮所有思考、工具调用和结果的列表
        core_wisdom: 提炼的核心智慧（300字以内）
        next_goal: 下一世代的目标
    
    Returns:
        归档结果，包含文件路径
    """
    archives_path = _get_archives_path()
    
    archive = {
        "generation": generation,
        "archived_at": datetime.now().isoformat(),
        "core_wisdom": core_wisdom,
        "next_goal": next_goal,
        "total_steps": len(history_data),
        "history": history_data,
    }
    
    filename = f"gen_{generation}_history.json"
    filepath = os.path.join(archives_path, filename)
    
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(archive, f, ensure_ascii=False, indent=2)
        
        return json.dumps({
            "status": "success",
            "generation": generation,
            "archive_file": filepath,
            "steps_count": len(history_data),
            "message": f"世代 G{generation} 档案已归档至 {filename}"
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({
            "status": "error",
            "message": f"归档失败: {str(e)}"
        }, ensure_ascii=False)


def read_generation_archive_tool(generation: int) -> str:
    """
    读取指定世代的详细档案。
    
    Args:
        generation: 世代编号
    
    Returns:
        世代档案的JSON字符串
    """
    archives_path = _get_archives_path()
    filename = f"gen_{generation}_history.json"
    filepath = os.path.join(archives_path, filename)
    
    if not os.path.exists(filepath):
        return json.dumps({
            "status": "error",
            "message": f"世代 G{generation} 的档案不存在"
        }, ensure_ascii=False)
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            archive = json.load(f)
        return json.dumps(archive, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({
            "status": "error",
            "message": f"读取档案失败: {str(e)}"
        }, ensure_ascii=False)


def list_archives_tool() -> str:
    """
    列出所有可用的世代档案。
    
    Returns:
        档案列表
    """
    archives_path = _get_archives_path()
    
    if not os.path.exists(archives_path):
        return json.dumps({
            "status": "success",
            "archives": [],
            "message": "暂无档案记录"
        }, ensure_ascii=False)
    
    archives = []
    for filename in sorted(os.listdir(archives_path)):
        if filename.startswith("gen_") and filename.endswith("_history.json"):
            filepath = os.path.join(archives_path, filename)
            try:
                stat = os.stat(filepath)
                archives.append({
                    "filename": filename,
                    "size_bytes": stat.st_size,
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                })
            except OSError:
                pass
    
    return json.dumps({
        "status": "success",
        "archives": archives,
        "count": len(archives)
    }, ensure_ascii=False)


def commit_compressed_memory_tool(new_core_context: str, next_goal: str) -> str:
    """
    更新记忆索引。
    
    【极度重要】在调用 trigger_self_restart 之前必须调用此函数！
    会更新 core_wisdom 和 current_goal，世代号由归档操作递增。
    
    Args:
        new_core_context: 压缩后的新上下文摘要（建议不超过300字）
        next_goal: 下一代需要接着做的具体任务
        
    Returns:
        更新后的JSON字符串，包含状态和世代信息
    """
    if len(new_core_context) > 300:
        new_core_context = new_core_context[:297] + "..."
    
    memory = _load_memory()
    memory["core_wisdom"] = new_core_context
    memory["current_goal"] = next_goal
    memory["last_archive_time"] = datetime.now().isoformat()
    
    if _save_memory(memory):
        return json.dumps({
            "status": "success",
            "current_generation": memory["current_generation"],
            "total_generations": memory.get("total_generations", 1),
            "core_wisdom": new_core_context,
            "next_goal": next_goal,
            "message": f"记忆索引已更新"
        }, ensure_ascii=False)
    else:
        return json.dumps({
            "status": "error",
            "message": "记忆保存失败，请检查文件权限"
        }, ensure_ascii=False)


def force_save_current_state(core_wisdom: str = "", next_goal: str = "", generation: int = None) -> str:
    """
    【强制记忆快照】在重启前自动调用，确保记忆被保存。

    Args:
        core_wisdom: 核心智慧摘要（可选，如果为空则保留原有值）
        next_goal: 下一世代目标（可选，如果为空则保留原有值）
        generation: 当前世代（可选，如果为空则读取原有值）

    Returns:
        保存结果
    """
    from core.logging import debug_logger

    try:
        memory = _load_memory()

        if not core_wisdom:
            core_wisdom = memory.get("core_wisdom", "无")
        if not next_goal:
            next_goal = memory.get("current_goal", "待定")
        if generation is None:
            generation = memory.get("current_generation", 1)

        if len(core_wisdom) > 300:
            core_wisdom = core_wisdom[:297] + "..."

        memory["core_wisdom"] = core_wisdom
        memory["current_goal"] = next_goal
        memory["current_generation"] = generation
        memory["last_archive_time"] = datetime.now().isoformat()

        if _save_memory(memory):
            debug_logger.warning(f"[强制快照] 记忆已保存: G{generation}")
            return json.dumps({
                "status": "success",
                "message": f"强制记忆快照完成: G{generation}",
                "core_wisdom": core_wisdom,
                "next_goal": next_goal
            }, ensure_ascii=False)
        else:
            debug_logger.error("[ERROR] 强制记忆快照失败")
            return json.dumps({
                "status": "error",
                "message": "强制记忆快照失败"
            }, ensure_ascii=False)

    except Exception as e:
        debug_logger.error(f"[ERROR] 强制记忆快照异常: {e}")
        return json.dumps({
            "status": "error",
            "message": f"强制记忆快照异常: {str(e)}"
        }, ensure_ascii=False)


def advance_generation() -> int:
    """
    推进到下一世代（内部使用，由归档操作调用）。
    
    Returns:
        新的世代编号
    """
    memory = _load_memory()
    current = memory.get("current_generation", 1)
    memory["current_generation"] = current + 1
    memory["total_generations"] = max(memory.get("total_generations", 1), current + 1)
    _save_memory(memory)
    return current + 1


# ============================================================================
# 动态提示词管理工具
# ============================================================================

def read_dynamic_prompt_tool() -> str:
    """
    读取当前的动态提示词内容。
    
    Returns:
        动态提示词的原始文本
    """
    try:
        if os.path.exists(_get_dynamic_prompt_path()):
            with open(_get_dynamic_prompt_path(), 'r', encoding='utf-8') as f:
                return f.read()
        return "动态提示词为空"
    except Exception as e:
        return f"[错误: 无法读取动态提示词: {e}]"


def update_generation_task_tool(task: str) -> str:
    """
    更新当前世代的任务到动态提示词区域。
    
    Args:
        task: 当前世代的任务描述（建议使用 Markdown 格式）
        
    Returns:
        更新结果
    """
    try:
        current_gen = _load_memory().get("current_generation", 1)
        
        if os.path.exists(_get_dynamic_prompt_path()):
            with open(_get_dynamic_prompt_path(), 'r', encoding='utf-8') as f:
                existing_content = f.read()
        else:
            existing_content = "# 动态提示词区域\n\n*此区域由模型在每个世代开始时动态生成*\n\n---\n\n"
        
        # 提取累积的洞察（保留世代积累的智慧）
        insights = ""
        if "## 积累的洞察" in existing_content:
            match = re.search(r"(## 积累的洞察.*)", existing_content, re.DOTALL)
            if match:
                insights = match.group(1).strip()
        
        new_content = f"""# 动态提示词区域

*此区域由模型在每个世代开始时动态生成，会自动加载到系统提示词中。*

---

## G{current_gen} 世代任务

{task}
"""
        
        if insights:
            new_content += f"\n---\n\n{insights}\n"
        
        with open(_get_dynamic_prompt_path(), 'w', encoding='utf-8') as f:
            f.write(new_content)
        
        return json.dumps({
            "status": "success",
            "message": f"G{current_gen} 世代任务已更新",
            "generation": current_gen,
            "task_preview": task[:100] + "..." if len(task) > 100 else task,
        }, ensure_ascii=False)
        
    except Exception as e:
        return json.dumps({
            "status": "error",
            "message": f"更新世代任务失败: {str(e)}"
        }, ensure_ascii=False)


def add_insight_to_dynamic_tool(insight: str) -> str:
    """
    将洞察追加到动态提示词的积累区域。
    
    Args:
        insight: 要追加的洞察内容
        
    Returns:
        更新结果
    """
    try:
        current_gen = _load_memory().get("current_generation", 1)
        
        if os.path.exists(_get_dynamic_prompt_path()):
            with open(_get_dynamic_prompt_path(), 'r', encoding='utf-8') as f:
                existing_content = f.read()
        else:
            existing_content = ""
        
        if "## 积累的洞察" in existing_content:
            pattern = r"(## 积累的洞察\n\n)"
            replacement = rf"\1**G{current_gen}**: {insight}\n\n"
            updated_content = re.sub(pattern, replacement, existing_content)
        else:
            if existing_content.strip():
                updated_content = existing_content.rstrip() + f"\n\n---\n\n## 积累的洞察\n\n**G{current_gen}**: {insight}\n"
            else:
                updated_content = f"""# 动态提示词区域

*此区域由模型在每个世代开始时动态生成*

---

## 积累的洞察

**G{current_gen}**: {insight}
"""
        
        with open(_get_dynamic_prompt_path(), 'w', encoding='utf-8') as f:
            f.write(updated_content)
        
        return json.dumps({
            "status": "success",
            "message": "洞察已追加到动态提示词",
            "generation": current_gen,
        }, ensure_ascii=False)
        
    except Exception as e:
        return json.dumps({
            "status": "error",
            "message": f"追加洞察失败: {str(e)}"
        }, ensure_ascii=False)


def write_dynamic_prompt_tool(content: str) -> str:
    """
    【完整写入动态提示词】用新内容完整替换 DYNAMIC.md 的正文内容。

    与 add_insight_to_dynamic_tool 的"追加洞察"不同，本工具执行全量覆盖写入，
    适用于重写整个动态提示词区域的场景。

    Args:
        content: 新的动态提示词完整内容

    Returns:
        JSON 格式结果
    """
    try:
        import hashlib
        current_gen = _load_memory().get("current_generation", 1)

        new_content = f"""# 动态提示词区域

{content}
"""
        path = _get_dynamic_prompt_path()
        with open(path, 'w', encoding='utf-8') as f:
            f.write(new_content)

        size = len(content)
        preview = content[:80] + "..." if len(content) > 80 else content

        return json.dumps({
            "status": "success",
            "message": "动态提示词已更新",
            "generation": current_gen,
            "content_hash": hashlib.md5(content.encode()).hexdigest()[:8],
            "size_bytes": size,
            "preview": preview,
        }, ensure_ascii=False)

    except Exception as e:
        return json.dumps({
            "status": "error",
            "message": f"写入动态提示词失败: {str(e)}"
        }, ensure_ascii=False)


def clear_generation_task() -> str:
    """
    清除世代任务区域，为下一世代做准备。
    
    Returns:
        操作结果
    """
    try:
        if not os.path.exists(_get_dynamic_prompt_path()):
            return "无需清除（DYNAMIC.md 不存在）"
        
        with open(_get_dynamic_prompt_path(), 'r', encoding='utf-8') as f:
            existing_content = f.read()
        
        insights = ""
        if "## 积累的洞察" in existing_content:
            match = re.search(r"(## 积累的洞察.*)", existing_content, re.DOTALL)
            if match:
                insights = match.group(1).strip()
        
        next_gen = _load_memory().get("current_generation", 1) + 1
        
        if insights:
            new_content = f"""# 动态提示词区域

*此区域由模型在每个世代开始时动态生成*

---

## G{next_gen} 世代任务

<!-- 模型将在此区域生成当前世代的任务 -->

---

{insights}
"""
        else:
            new_content = f"""# 动态提示词区域

*此区域由模型在每个世代开始时动态生成*

---

## G{next_gen} 世代任务

<!-- 模型将在此区域生成当前世代的任务 -->
"""
        
        with open(_get_dynamic_prompt_path(), 'w', encoding='utf-8') as f:
            f.write(new_content)
        
        return f"G{next_gen} 世代任务区域已准备"
        
    except Exception as e:
        return f"清除任务区域失败: {str(e)}"


# 保持向后兼容
update_dynamic_prompt = update_generation_task_tool


# ============================================================================
# 代码库认知地图工具
# ============================================================================

def record_codebase_insight_tool(module_path: str, insight: str) -> str:
    """
    刻印代码库认知到数据库

    .. deprecated::
        此工具已废弃。请通过 PromptManager 的 CODEBASE_MAP 组件
        自动注入动态 AST 扫描结果，无需手动刻印。
        若需强制刷新地图，可调用：
        ``from core.capabilities.codebase_map_builder import get_codebase_map; get_codebase_map(force_refresh=True)``

    Args:
        module_path: 模块路径，如 'tools/ast_tools.py' 或 '整体架构'
        insight: 该模块的核心作用、已知问题或最佳调用方式

    Returns:
        操作结果
    """
    import warnings
    warnings.warn(
        "record_codebase_insight_tool is deprecated. "
        "Use core.capabilities.codebase_map_builder.get_codebase_map() instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    try:
        ws = get_workspace()
        current_gen = get_generation_tool()

        success = ws.record_codebase_insight(module_path, insight, current_gen)

        if success:
            return f"✅ 已刻印到数据库: [{module_path}] G{current_gen}\n\n认知摘要: {insight[:100]}..."
        else:
            return f"❌ 刻印失败: {module_path}"

    except Exception as e:
        return f"❌ 刻印异常: {str(e)}"


def get_global_codebase_map_tool() -> str:
    """
    获取全局代码库认知地图

    .. deprecated::
        此工具已废弃。请通过 PromptManager 的 CODEBASE_MAP 组件
        自动注入动态 AST 扫描结果，无需手动调用。
        若需强制刷新地图，可调用：
        ``from core.capabilities.codebase_map_builder import get_codebase_map; get_codebase_map(force_refresh=True)``

    Returns:
        Markdown 格式的认知地图
    """
    import warnings
    warnings.warn(
        "get_global_codebase_map_tool is deprecated. "
        "Use core.capabilities.codebase_map_builder.get_codebase_map() instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    try:
        ws = get_workspace()
        return ws.generate_codebase_map()

    except Exception as e:
        return f"[警告] 获取认知地图失败: {str(e)}"


# ============================================================================
# 任务管理工具
# ============================================================================

def set_plan_tool(goal: str, tasks: List[str]) -> str:
    """
    【计划制定工具】设置本轮任务清单

    Args:
        goal: 本轮的总目标描述（如 "重构错误重试逻辑"）
        tasks: 子任务列表（3-5个），每个任务描述要具体可执行

    Returns:
        格式化的任务列表
    """
    # 类型守卫：防止传入字符串被当作字符列表处理
    if isinstance(tasks, str):
        # 如果是单个任务字符串，包装成列表
        tasks = [tasks]
    elif not isinstance(tasks, list):
        return "[❌ 错误] tasks 参数必须是字符串列表，而非 " + type(tasks).__name__

    # 过滤空字符串
    tasks = [t for t in tasks if t and t.strip()]
    if not tasks:
        return "[❌ 错误] tasks 列表不能为空"

    result = get_task_manager().set_plan(goal, tasks)
    
    lines = [
        f"[✅ 任务清单已设置]",
        f"",
        f"🎯 目标: {result['goal']}",
        f"",
        f"📋 子任务 ({result['pending_count']} 项):",
    ]
    
    for task in result.get("tasks", []):
        desc = task['description']
        # 去掉描述中已有的 "1. " / "1、" / "1)" 前缀，避免显示重复编号
        desc = re.sub(r'^(\d+)[.、)]\s*', '', desc).strip()
        lines.append(f"  ⏳ [ ] {task['id']}. {desc}")
    
    lines.append("")
    lines.append("请开始执行，完成后用 tick_subtask 逐个打勾！")
    
    return "\n".join(lines)


def tick_subtask_tool(task_id: int, summary: str) -> str:
    """
    【任务打勾工具】标记任务完成并记录结论

    Args:
        task_id: 任务编号
        summary: 该任务完成后的核心结论/成果

    Returns:
        完成进度信息
    """
    result = get_task_manager().tick_subtask(task_id, summary)
    
    if result["status"] != "success":
        return f"[❌ 错误] {result.get('message', '未知错误')}"
    
    completed = result["completed_count"]
    total = result["total"]
    remaining = result["remaining"]
    all_done = result.get("all_done", False)
    
    lines = [
        f"[✅ 任务 #{task_id} 已完成]",
        f"",
        f"📝 结论: {summary}",
        f"",
        f"📊 进度: {completed}/{total}",
    ]
    
    if all_done:
        lines.extend([
            "",
            "🎉 【全部任务完成！】",
            "你现在可以调用 trigger_self_restart 结束本轮了！",
        ])
    else:
        lines.extend([
            "",
            f"⏳ 还剩 {remaining} 个任务，继续加油！",
        ])
    
    return "\n".join(lines)


def modify_task_tool(task_id: int, new_description: str) -> str:
    """
    【任务修改工具】修改任务描述

    Args:
        task_id: 任务编号
        new_description: 新的任务描述

    Returns:
        修改结果
    """
    result = get_task_manager().modify_task(task_id, new_description)
    
    if result["status"] == "success":
        return f"[✅ 任务 #{task_id} 已修改]: {new_description}"
    return f"[❌ 错误] {result.get('message', '未知错误')}"


def add_task_tool(description: str) -> str:
    """
    【任务追加工具】添加新的子任务

    Args:
        description: 新任务描述

    Returns:
        添加结果
    """
    result = get_task_manager().add_task(description)
    
    if result["status"] == "success":
        return f"[✅ 新任务已添加] #{result['task_id']}: {description}"
    return f"[❌ 错误] {result.get('message', '未知错误')}"


def remove_task_tool(task_id: int) -> str:
    """
    【任务删除工具】删除不需要的任务

    Args:
        task_id: 要删除的任务编号

    Returns:
        删除结果
    """
    result = get_task_manager().remove_task(task_id)
    
    if result["status"] == "success":
        return f"[✅ 任务 #{task_id} 已删除]，剩余 {result['remaining']} 个任务"
    return f"[❌ 错误] {result.get('message', '未知错误')}"


def check_restart_block_tool() -> tuple[bool, str]:
    """
    【系统内部】检查是否允许重启

    Returns:
        (is_blocked: bool, message: str)
    """
    tm = get_task_manager()
    
    if not tm.subtasks:
        return False, ""
    
    if not tm.is_all_completed:
        pending_tasks = [t for t in tm.subtasks if not t["is_completed"]]
        pending_list = "\n".join([
            f"  ⏳ [ ] {t['id']}. {t['description']}"
            for t in pending_tasks
        ])
        
        message = (
            f"\n"
            f"[系统拦截] 你的任务清单中还有未完成的项目，禁止重启！\n"
            f"\n"
            f"📋 未完成任务 ({len(pending_tasks)} 项):\n"
            f"{pending_list}\n"
            f"\n"
            f"请继续执行剩余任务，或使用 modify_task / remove_task 调整计划。\n"
            f"禁止调用 trigger_self_restart 直到所有任务都打勾！\n"
        )
        return True, message
    
    return False, ""


def check_restart_block() -> tuple[bool, str]:
    """【内部别名】check_restart_block_tool 的无后缀版本，供 agent.py 调用"""
    return check_restart_block_tool()


def get_task_status_tool() -> str:
    """
    【状态查询工具】查看当前任务状态

    Returns:
        当前任务清单的状态摘要
    """
    tm = get_task_manager()
    
    lines = [
        "[任务状态]",
        "",
        f"🎯 目标: {tm.generation_goal or '(未设置)'}",
        f"📊 进度: {tm.completion_rate:.0%}",
    ]
    
    if tm.subtasks:
        completed = sum(1 for t in tm.subtasks if t["is_completed"])
        lines.append(f"📋 任务: {completed}/{len(tm.subtasks)} 完成")
    else:
        lines.append("📋 任务: (空)")
    
    return "\n".join(lines)
