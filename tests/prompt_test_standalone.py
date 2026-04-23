# -*- coding: utf-8 -*-
"""
独立打靶测试 - 绕过 rich 的 Windows 崩溃问题
复用 prompt_debugger.py 的 LLM 调用逻辑
"""
import sys
import time
import re
import json
import builtins

# 重定向所有 print 到文件（绕过 Windows Python 3.14 stdout 崩溃）
_log_file = open("tests/test_output.log", "w", encoding="utf-8")
_orig_print = builtins.print
def _safe_print(*args, **kwargs):
    kwargs["file"] = _log_file
    kwargs["flush"] = True
    try:
        _orig_print(*args, **kwargs)
    except Exception:
        pass
builtins.print = _safe_print

sys.path.insert(0, ".")

def _build_llm_client(model: str, api_base: str, api_key: str, timeout: int = 300):
    """构建 LLM client（复用 agent.py 中的 MiniMaxOpenAIAdapter）"""
    import httpx
    from agent import MiniMaxOpenAIAdapter
    client = MiniMaxOpenAIAdapter(
        model=model,
        api_key=api_key or "",
        base_url=api_base or "https://api.minimaxi.com/v1",
        timeout=httpx.Timeout(timeout, connect=30),
    )
    return client

def _invoke_llm(client, model, system_prompt, user_prompt, tools):
    from langchain_core.messages import HumanMessage, SystemMessage
    messages = [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]
    response = client.invoke(messages)
    return response.content

def _parse_response(content):
    thinking = ""
    context_summary = ""
    tool_calls = []
    m = re.search(r'<thinking>\s*([\s\S]*?)\s*</thinking>', content)
    if m:
        thinking = m.group(1).strip()
    m = re.search(r'<context_summary>\s*([\s\S]*?)\s*</context_summary>', content)
    if m:
        context_summary = m.group(1).strip()
    for m in re.finditer(r'<tool_call>\s*(\{[\s\S]*?\})\s*</tool_call>', content):
        try:
            tool_calls.append(json.loads(m.group(1)))
        except json.JSONDecodeError:
            tool_calls.append({"raw": m.group(1)})
    return thinking, context_summary, tool_calls

def run_test(client, model, system_prompt, prompt, expect_tool, description):
    print(f"\n{'='*60}")
    print(f"测试: {description}")
    print(f"Prompt: {prompt}")
    print("-" * 60)

    t0 = time.time()
    try:
        raw = _invoke_llm(client, model, system_prompt, prompt, [])
        thinking, _, tool_calls = _parse_response(raw)
        duration_ms = (time.time() - t0) * 1000

        called_tools = [tc.get("name") or tc.get("type", "?") for tc in tool_calls]
        matched = expect_tool in called_tools if expect_tool else True

        print(f"状态: {'PASS' if matched else 'FAIL'}")
        print(f"耗时: {duration_ms:.0f}ms")
        print(f"期望工具: {expect_tool or '无'}")
        print(f"实际工具: {called_tools if called_tools else '(无)'}")
        if thinking:
            print(f"思考: {thinking[:200]}...")

        return {
            "name": description, "pass": matched,
            "expect": expect_tool, "called": called_tools,
            "duration_ms": duration_ms, "error": None
        }
    except Exception as e:
        duration_ms = (time.time() - t0) * 1000
        print(f"错误: {type(e).__name__}: {e}")
        return {
            "name": description, "pass": False,
            "expect": expect_tool, "called": [],
            "duration_ms": duration_ms, "error": str(e)
        }

def main():
    print("初始化...")
    from core.prompt_manager.prompt_manager import get_prompt_manager

    # 加载配置
    from config import get_config
    cfg = get_config()
    api_key = cfg.get_api_key()
    api_base = cfg.llm.api_base
    model_name = cfg.llm.model_name

    client = _build_llm_client(model_name, api_base, api_key, timeout=300)

    pm = get_prompt_manager()
    system_prompt = pm.build()
    print(f"System Prompt 已加载 ({len(system_prompt)} 字)\n")

    suites = [
        {"name": "记忆注入验证", "description": "MEMORY 组件注入",
         "prompt": "请介绍你自己，包括你的代号、核心目标。", "expect_tool": None},
        {"name": "read_dynamic_prompt_tool", "description": "读取 DYNAMIC.md",
         "prompt": "请读取 workspace/prompts/DYNAMIC.md 的内容，然后告诉我当前世代的任务目标是什么。",
         "expect_tool": "read_dynamic_prompt_tool"},
        {"name": "write_dynamic_prompt_tool", "description": "写入 DYNAMIC.md",
         "prompt": "请更新 workspace/prompts/DYNAMIC.md，在其中写入你完成的一个任务记录。",
         "expect_tool": "write_dynamic_prompt_tool"},
        {"name": "set_plan_tool", "description": "制定任务计划",
         "prompt": "请制定一个计划，包含3个步骤来完成'了解项目结构'这个任务。",
         "expect_tool": "set_plan_tool"},
        {"name": "read_memory_tool", "description": "读取记忆",
         "prompt": "请读取当前记忆，然后告诉我你的当前世代和核心目标是什么。",
         "expect_tool": "read_memory_tool"},
        {"name": "commit_compressed_memory_tool", "description": "压缩记忆存盘",
         "prompt": "请调用 commit_compressed_memory_tool，核心发现写'打靶测试'，next_goal 写'继续测试'。",
         "expect_tool": "commit_compressed_memory_tool"},
        {"name": "check_python_syntax_tool", "description": "语法检查",
         "prompt": "请检查 tools/memory_tools.py 的语法是否正确。",
         "expect_tool": "check_python_syntax_tool"},
        {"name": "enter_hibernation_tool", "description": "休眠工具",
         "prompt": "请调用 enter_hibernation_tool 休眠 10 秒。",
         "expect_tool": "enter_hibernation_tool"},
        {"name": "backup_project_tool", "description": "备份项目",
         "prompt": "请备份当前项目，备注为'打靶测试'。",
         "expect_tool": "backup_project_tool"},
        {"name": "cleanup_test_files_tool", "description": "清理测试文件",
         "prompt": "请调用 cleanup_test_files_tool，扫描当前目录的测试临时文件。",
         "expect_tool": "cleanup_test_files_tool"},
        {"name": "grep_search_tool", "description": "正则搜索",
         "prompt": "请使用 grep_search_tool 搜索项目中所有包含 'def commit_compressed_memory_tool' 的文件。",
         "expect_tool": "grep_search_tool"},
        {"name": "list_file_entities_tool", "description": "AST 透视",
         "prompt": "请用 list_file_entities_tool 分析 tools/memory_tools.py 的文件结构。",
         "expect_tool": "list_file_entities_tool"},
    ]

    results = []
    for suite in suites:
        result = run_test(client, model_name, system_prompt,
                          suite["prompt"], suite["expect_tool"], suite["name"])
        results.append(result)
        time.sleep(1)

    print(f"\n{'='*60}")
    print("测试套件汇总")
    print("-" * 60)
    for r in results:
        status = "PASS" if r["pass"] else "FAIL"
        print(f"  [{status}] {r['name']:<35} 期望: {str(r['expect']):<30}  实际: {r['called'] if r['called'] else '无'}")

    passed = sum(1 for r in results if r["pass"])
    print(f"\n通过率: {passed}/{len(results)} ({100*passed/len(results):.0f}%)")

if __name__ == "__main__":
    try:
        main()
    finally:
        _log_file.close()
        builtins.print = _orig_print
        # Also restore stderr
        try:
            import sys
            sys.stderr.flush()
        except Exception:
            pass
