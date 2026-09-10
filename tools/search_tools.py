#!/usr/bin/env python3
"""
全局搜索工具 - 模拟 IDE 的全局正则检索

提供类似 Cursor/Aider 的全局代码搜索能力，支持：
1. 正则表达式全文搜索
2. 文件类型过滤
3. 大文件智能处理
4. 匹配上下文展示
"""

import json
import logging
import re
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable, Optional, List, Tuple, Dict

logger = logging.getLogger(__name__)

# ============================================================================
# 配置常量 - 从配置文件加载
# ============================================================================


def _load_search_defaults() -> dict:
    """从配置加载默认常量"""
    try:
        from config import get_config
        cfg = get_config()
        return {
            "MAX_FILE_SIZE": cfg.tools.search.max_file_size,
            "MAX_MATCHES_PER_FILE": cfg.tools.search.max_matches_per_file,
            "MAX_RESULTS": cfg.tools.search.max_results,
            "MAX_CONTEXT_LINES": cfg.tools.search.context_lines,
            "SKIP_DIRS": set(cfg.tools.search.skip_directories),
            "SKIP_EXTENSIONS": set(cfg.tools.search.skip_extensions),
            "INCLUDE_EXTENSIONS": set(cfg.tools.search.include_extensions),
            "RIPGREP_PATH": (getattr(cfg.tools.search, "ripgrep_path", "") or "").strip(),
            "GREP_DEADLINE_SECONDS": getattr(cfg.tools.search, "grep_deadline_seconds", 25.0),
        }
    except Exception:
        return {}


_search_defaults = _load_search_defaults()

# 搜索配置
MAX_FILE_SIZE = _search_defaults.get("MAX_FILE_SIZE", 10 * 1024 * 1024)
# 每个文件最大匹配数（强制上限50，防止单文件上下文爆炸）
MAX_MATCHES_PER_FILE = min(_search_defaults.get("MAX_MATCHES_PER_FILE", 100), 50)
MAX_CONTEXT_LINES = _search_defaults.get("MAX_CONTEXT_LINES", 3)
# grep 结果总数：从配置接通 max_results 键，并保留 50 的强制钳制
MAX_RESULTS_CONFIG_CAP = 50
SKIP_DIRS = _search_defaults.get("SKIP_DIRS", {
    '__pycache__', '.git', '.svn', '.hg', 'node_modules',
    '.venv', 'venv', 'env', '.env', '.idea', '.vscode',
    'dist', 'build', '.tox', '.pytest_cache', '.mypy_cache',
    'site-packages', 'egg-info', '.eggs',
    '.worktrees', '.runtime', 'instances'
})
SKIP_EXTENSIONS = _search_defaults.get("SKIP_EXTENSIONS", {'.exe', '.dll', '.so', '.dylib', '.pyc', '.pyo', '.pyd'})
INCLUDE_EXTENSIONS = _search_defaults.get("INCLUDE_EXTENSIONS", {
    '.py', '.js', '.ts', '.jsx', '.tsx', '.md', '.json', '.yaml', '.yml', '.toml', '.txt', '.html', '.css', '.xml', '.sh', '.bat', '.ps1'
})

EXTENSION_FAMILIES = {
    ".js": {".js", ".jsx"},
    ".ts": {".ts", ".tsx"},
}


def _normalize_path(file_path: str) -> Path:
    """规范化文件路径"""
    return Path(file_path).resolve()


def _should_skip_path(path: Path) -> bool:
    """检查是否应该跳过该路径"""
    parts = path.parts
    for skip_dir in SKIP_DIRS:
        if skip_dir in parts:
            return True
    return False


def _should_process_file(file_path: Path) -> bool:
    """检查是否应该处理该文件"""
    if not file_path.is_file():
        return False
    if file_path.suffix.lower() in SKIP_EXTENSIONS:
        return False
    try:
        size = file_path.stat().st_size
        if size > MAX_FILE_SIZE:
            return False
    except OSError:
        return False
    return True


def _resolve_extensions(include_ext: str) -> set[str]:
    """把公开扩展名参数解析为实际扩展集合。"""
    if include_ext == "*":
        return INCLUDE_EXTENSIONS
    if include_ext.startswith("."):
        normalized = include_ext.lower()
    else:
        normalized = f".{include_ext.lstrip('.')}".lower()
    return EXTENSION_FAMILIES.get(normalized, {normalized})


def _looks_like_redos_pattern(pattern: str) -> bool:
    """轻量检测常见 ReDoS 形态，避免高危嵌套量词。"""
    if not pattern:
        return False
    heuristics = [
        r"\([^)]*[+*][^)]*\)[+*?]",   # (a+)+ / (.*)* / (.+)?
        r"\([^)]*\{[^}]+\}[^)]*\)[+*?]",  # (a{1,3})+
    ]
    return any(re.search(rule, pattern) for rule in heuristics)


# ============================================================================
# 搜索基准目录解析 - 相对路径不得落到后端进程 CWD
# ============================================================================

def _resolve_search_root(search_dir: str) -> Path:
    """解析搜索基准目录。

    绝对路径原样使用；相对路径（含默认 "."）优先锚定到 workspace override，
    其次项目根，避免解析到后端进程 CWD 造成全仓扫描。
    """
    raw = str(search_dir or "").strip() or "."
    path = Path(raw)
    if path.is_absolute():
        return path.resolve()
    anchor: Optional[Path] = None
    try:
        from tools.shell_tools import get_workspace_root_override
        override = get_workspace_root_override()
        if override is not None and (override / ".git").exists():
            anchor = override
    except Exception:
        anchor = None
    if anchor is None:
        anchor = Path(__file__).resolve().parents[1]
    return (anchor / path).resolve()


# ============================================================================
# ripgrep 子进程引擎（主）与纯 Python 扫描引擎（回退）
#
# 设计要点：
# 1. rg 主引擎走 argv + shell=False + CREATE_NO_WINDOW（§8.0 无控制台红线）。
# 2. rg 进程可被 kill：超时/取消后 kill + 二次 communicate 回收部分输出，
#    解析为「部分结果 + 截断标志」，绝不返回裸错误字符串。
# 3. 纯 Python 回退引擎在 os.walk 每轮目录间检查 deadline 与 cancel checker，
#    到点停止扫描并返回已收集的部分结果。
# ============================================================================

_RG_POLL_INTERVAL_SECONDS = 0.25
_RG_MAX_COLUMNS = 300
# 定案参数面：-m 200 限制 rg 单文件输出上限，最终结果仍按 per-file/总量钳制
_RG_PER_FILE_MATCH_CAP = 200
# grep 软超时默认值；必须小于 tool executor 的 30 秒硬门
_GREP_DEADLINE_DEFAULT_SECONDS = 25.0
_GREP_DEADLINE_HARD_CAP_SECONDS = 29.0

GREP_DEADLINE_SECONDS = max(
    1.0,
    min(
        float(_search_defaults.get("GREP_DEADLINE_SECONDS", _GREP_DEADLINE_DEFAULT_SECONDS) or _GREP_DEADLINE_DEFAULT_SECONDS),
        _GREP_DEADLINE_HARD_CAP_SECONDS,
    ),
)

_rg_probe_lock = threading.Lock()
_rg_probe_done = False
_rg_executable: Optional[str] = None


def reset_ripgrep_detection() -> None:
    """重置 rg 探测缓存（配置热更或测试使用）。"""
    global _rg_probe_done, _rg_executable
    with _rg_probe_lock:
        _rg_probe_done = False
        _rg_executable = None


def _detect_ripgrep() -> Optional[str]:
    """惰性探测一次 rg 可执行文件：配置显式路径 → PATH。

    探测失败返回 None 并 log 一次，调用方静默回退纯 Python 引擎。
    """
    global _rg_probe_done, _rg_executable
    with _rg_probe_lock:
        if _rg_probe_done:
            return _rg_executable
        candidate = ""
        configured = str(_search_defaults.get("RIPGREP_PATH", "") or "").strip()
        if configured:
            configured_path = Path(configured)
            if configured_path.is_file():
                candidate = str(configured_path)
            else:
                logger.warning(
                    "[grep] tools.search.ripgrep_path 指向的文件不存在，回退 PATH 探测: %s",
                    configured,
                )
        if not candidate:
            try:
                found = shutil.which("rg")
                candidate = str(found) if found else ""
            except Exception:
                candidate = ""
        _rg_probe_done = True
        _rg_executable = candidate or None
        if not candidate:
            logger.warning(
                "[grep] 未探测到 ripgrep (rg)，grep_search_tool 使用纯 Python 扫描引擎；"
                "如需提速请安装 rg 或配置 tools.search.ripgrep_path"
            )
        return _rg_executable


def _build_ripgrep_command(
    rg_executable: str,
    pattern: str,
    target_path: Path,
    *,
    extensions: set,
    case_sensitive: bool,
    context_lines: int,
) -> List[str]:
    """构造 rg 命令行。pattern 走 -e、路径放 -- 之后，--no-config 必加。"""
    cmd: List[str] = [
        rg_executable,
        "--json",
        "--no-config",
        "--no-messages",
        f"--max-filesize={MAX_FILE_SIZE}",
        f"--max-columns={_RG_MAX_COLUMNS}",
        "--max-columns-preview",
        f"--max-count={_RG_PER_FILE_MATCH_CAP}",
    ]
    if not case_sensitive:
        cmd.append("--ignore-case")
    if context_lines > 0:
        cmd.extend(["--after-context", str(context_lines)])
        cmd.extend(["--before-context", str(context_lines)])
    for ext in sorted(extensions):
        cmd.extend(["--glob", f"*{ext}"])
    for ext in sorted(SKIP_EXTENSIONS):
        cmd.extend(["--glob", f"!*{ext}"])
    for skip_dir in sorted(SKIP_DIRS):
        cmd.extend(["--glob", f"!{skip_dir}"])
    cmd.extend(["-e", pattern])
    cmd.append("--")
    cmd.append(str(target_path))
    return cmd


def _run_ripgrep_with_deadline(
    cmd: List[str],
    deadline: float,
    cancel_checker: Optional[Callable[[], str]],
) -> Tuple[Optional[str], bool, str, Optional[int]]:
    """执行 rg 子进程并在 deadline/取消时 kill 回收。

    Returns:
        (stdout_text, killed, cancel_reason, returncode)；
        启动失败时 stdout_text 为 None（上层回退纯 Python 引擎）。
    """
    try:
        from scripts.windowless_subprocess import no_window_subprocess_kwargs
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            **no_window_subprocess_kwargs(),
        )
    except Exception as exc:
        logger.warning("[grep] ripgrep 启动失败，回退纯 Python 引擎: %s", exc)
        return None, False, "", None

    stdout_text: Optional[str] = None
    killed = False
    cancel_reason = ""
    while True:
        if callable(cancel_checker):
            try:
                cancel_reason = str(cancel_checker() or "").strip()
            except Exception:
                cancel_reason = ""
            if cancel_reason:
                killed = True
                break
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            killed = True
            break
        try:
            stdout_text, _ = proc.communicate(timeout=min(_RG_POLL_INTERVAL_SECONDS, remaining))
            break
        except subprocess.TimeoutExpired:
            continue

    if killed:
        try:
            proc.kill()
        except OSError:
            pass
        # 二次 communicate 回收 kill 前已产生的部分输出（rg 无子进程，kill 即够）
        try:
            partial_out, _ = proc.communicate()
            stdout_text = (stdout_text or "") + (partial_out or "")
        except Exception:
            pass

    return stdout_text, killed, cancel_reason, proc.poll()


def _parse_ripgrep_events(
    stdout_text: str,
    context_lines: int,
    target_filename: Optional[str],
) -> List[Tuple[str, int, str, List[str]]]:
    """解析 rg --json 输出为与纯 Python 引擎同构的 results 元组列表。"""
    line_text_by_file: Dict[str, Dict[int, str]] = {}
    matches_by_file: Dict[str, List[int]] = {}
    file_order: List[str] = []
    for raw_line in stdout_text.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        try:
            event = json.loads(stripped)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(event, dict):
            continue
        event_type = event.get("type")
        if event_type not in ("match", "context"):
            continue
        data = event.get("data") or {}
        path_text = str(((data.get("path") or {}).get("text")) or "")
        text = str(((data.get("lines") or {}).get("text")) or "")
        try:
            line_no = int(data.get("line_number") or 0)
        except (TypeError, ValueError):
            continue
        if not path_text or line_no <= 0:
            continue
        if path_text not in line_text_by_file:
            line_text_by_file[path_text] = {}
            matches_by_file[path_text] = []
            file_order.append(path_text)
        line_text_by_file[path_text][line_no] = text.rstrip("\r\n")
        if event_type == "match":
            matches_by_file[path_text].append(line_no)

    results: List[Tuple[str, int, str, List[str]]] = []
    for path_text in file_order:
        if target_filename and Path(path_text).name != target_filename:
            continue
        line_map = line_text_by_file[path_text]
        for line_no in matches_by_file[path_text][:MAX_MATCHES_PER_FILE]:
            context_start = max(1, line_no - context_lines)
            context_end = line_no + context_lines
            context = [line_map[i] for i in range(context_start, context_end + 1) if i in line_map]
            results.append((path_text, line_no, line_map.get(line_no, ""), context))
    return results


def _grep_via_ripgrep(
    pattern: str,
    regex_pattern: str,
    search_dir_path: Path,
    extensions: set,
    case_sensitive: bool,
    effective_context_lines: int,
    target_filename: Optional[str],
    max_results: int,
    deadline: float,
    cancel_checker: Optional[Callable[[], str]],
) -> Optional[Tuple[List[Tuple[str, int, str, List[str]]], bool, str]]:
    """rg 主引擎。返回 (results, incomplete, cancel_reason)；返回 None 表示回退纯 Python。"""
    rg_executable = _detect_ripgrep()
    if not rg_executable:
        return None

    rg_target = search_dir_path / target_filename if target_filename else search_dir_path
    if target_filename:
        # 与纯 Python 引擎契约对齐：单文件模式下扩展名不匹配或超大文件 → 零匹配
        target_suffix = Path(target_filename).suffix.lower()
        if extensions and target_suffix not in extensions:
            return [], False, ""
        try:
            if rg_target.stat().st_size > MAX_FILE_SIZE:
                return [], False, ""
        except OSError:
            return [], False, ""
    cmd = _build_ripgrep_command(
        rg_executable,
        pattern,
        rg_target,
        extensions=extensions,
        case_sensitive=case_sensitive,
        context_lines=effective_context_lines,
    )
    stdout_text, killed, cancel_reason, returncode = _run_ripgrep_with_deadline(cmd, deadline, cancel_checker)
    if stdout_text is None:
        return None

    results = _parse_ripgrep_events(stdout_text, effective_context_lines, target_filename)
    if not results and not killed and not cancel_reason and (returncode is None or returncode >= 2):
        # rg 约定：0=有匹配，1=无匹配，>=2=错误（如 Rust regex 不支持的 lookbehind 语法）。
        # 错误且无任何可回收输出时回退纯 Python 引擎；有部分输出则仍返回部分结果。
        return None
    if len(results) > max_results:
        results = results[:max_results]
    incomplete = bool(killed or cancel_reason)
    return results, incomplete, cancel_reason


def _grep_via_python(
    pattern: "re.Pattern",
    search_dir_path: Path,
    extensions: set,
    target_filename: Optional[str],
    effective_context_lines: int,
    max_results: int,
    deadline: float,
    cancel_checker: Optional[Callable[[], str]],
) -> Tuple[List[Tuple[str, int, str, List[str]]], bool, str]:
    """纯 Python 扫描引擎：os.walk 每轮目录间检查 deadline 与 cancel checker。"""
    results: List[Tuple[str, int, str, List[str]]] = []
    incomplete = False
    cancel_reason = ""
    stopped = False

    for root, dirs, files in os.walk(search_dir_path):
        # 过滤目录
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]

        if callable(cancel_checker):
            try:
                reason = str(cancel_checker() or "").strip()
            except Exception:
                reason = ""
            if reason:
                cancel_reason = reason
                stopped = True
                break

        if time.monotonic() > deadline:
            stopped = True
            break

        root_path = Path(root)

        for filename in files:
            file_path = root_path / filename

            if not _should_process_file(file_path):
                continue

            # 检查扩展名
            if extensions and file_path.suffix.lower() not in extensions:
                continue

            # 如果是单个文件模式，只处理目标文件
            if target_filename and filename != target_filename:
                continue

            # 跳过包含 skip 路径的文件
            if _should_skip_path(file_path):
                continue

            try:
                with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                    lines = f.readlines()
            except Exception:
                continue

            match_count = 0
            for line_num, line in enumerate(lines, 1):
                if pattern.search(line):
                    # 收集上下文
                    context_start = max(0, line_num - 1 - effective_context_lines)
                    context_end = min(len(lines), line_num + effective_context_lines)
                    context = [lines[i].rstrip() for i in range(context_start, context_end)]

                    results.append((
                        str(file_path),
                        line_num,
                        line.rstrip(),
                        context
                    ))
                    match_count += 1

                    if match_count >= MAX_MATCHES_PER_FILE:
                        break

                    if len(results) >= max_results:
                        break

            if len(results) >= max_results:
                break

        if len(results) >= max_results:
            break

        # 如果是单个文件模式，找到目标后就停止遍历
        if target_filename and results:
            break

    incomplete = stopped
    return results, incomplete, cancel_reason


def _format_grep_results(
    results: List[Tuple[str, int, str, List[str]]],
    regex_pattern: str,
    display_dir: Path,
    include_ext: str,
    effective_context_lines: int,
    max_output_chars: int,
    incomplete: bool = False,
    cancel_reason: str = "",
) -> str:
    """按既有契约格式化 grep 输出；超时/取消时追加显式截断提示。"""
    if not results:
        if incomplete:
            reason_note = f"已取消: {cancel_reason}" if cancel_reason else "已超时截断"
            return (
                f"[搜索] 未完成完整扫描（{reason_note}）；已收集 0 个匹配"
                "（结果不完整，建议收窄 pattern 或指定 search_dir）\n"
                f"正则: {regex_pattern}\n目录: {display_dir}\n类型: {include_ext}"
            )
        return f"[搜索] 未找到匹配项\n正则: {regex_pattern}\n目录: {display_dir}\n类型: {include_ext}"

    grouped: Dict[str, List[Tuple[int, str, List[str]]]] = {}
    for file_path, line_num, match_line, context in results:
        grouped.setdefault(file_path, []).append((line_num, match_line, context))

    output_lines = [
        f"[搜索] 正则: {regex_pattern}",
        f"[搜索] 目录: {display_dir}",
        f"[搜索] 类型: {include_ext}",
        f"[搜索] 找到 {len(results)} 个匹配，分布在 {len(grouped)} 个文件",
        "[搜索] 阅读策略: 先看文件分组与首个命中，再围绕命中行、目标符号或错误关键词读取局部上下文",
        "",
        "[搜索摘要]",
    ]

    for file_path, entries in grouped.items():
        line_numbers = [str(item[0]) for item in entries[:3]]
        more = f" ... +{len(entries) - 3}" if len(entries) > 3 else ""
        output_lines.append(
            f"- {file_path} | 命中 {len(entries)} 处 | 行 {', '.join(line_numbers)}{more}"
        )

    output_lines.extend(["", "=" * 80, "[搜索预览]"])

    max_output_chars = max(1200, int(max_output_chars or 8000))
    preview_file_limit = 3
    preview_match_limit = 6

    current_file = None
    chars_so_far = 0
    truncated = False
    preview_blocks = 0
    preview_matches = 0
    for file_path, line_num, match_line, context in results:
        if file_path != current_file:
            if preview_blocks >= preview_file_limit:
                truncated = True
                break
            current_file = file_path
            output_lines.append(f"\n📁 {file_path}")
            output_lines.append("-" * 80)
            preview_blocks += 1

        # 上下文行；match 行位于 context 中 index=min(ctx, line_num-1)
        # （两种引擎的 context 布局一致：文件开头/结尾截断后 match 前的行数变少）
        match_index = max(0, min(effective_context_lines, line_num - 1))
        for ctx_idx, ctx_line in enumerate(context):
            if ctx_idx == match_index:
                line = f"  → 第 {line_num} 行 | {ctx_line}"
            else:
                line = f"    第 {line_num - match_index + ctx_idx} 行 | {ctx_line}"
            output_lines.append(line)
            chars_so_far += len(line) + 1
            if chars_so_far > max_output_chars:
                truncated = True
                break

        if truncated:
            break
        preview_matches += 1
        if preview_matches >= preview_match_limit:
            truncated = True
            break

    if truncated:
        output_lines.append(f"\n... (搜索预览已截断，仅显示前 {preview_blocks} 个预览块)")
        if grouped:
            first_file = next(iter(grouped.keys()))
            output_lines.append(
                f'[阅读导航] 搜索结果仍有更多命中；不要默认从头分页读取 {first_file}。'
                "请围绕命中行、目标符号或错误关键词读取局部上下文。"
            )
        else:
            output_lines.append("[阅读导航] 缩小 regex_pattern / search_dir，或围绕目标文件的命中行读取局部上下文")
    else:
        output_lines.append("\n[阅读导航] 若需要更多上下文，请围绕上面命中的目标文件、行号或实体读取，不要默认线性翻页")

    output_lines.append("\n" + "=" * 80)
    output_lines.append(f"[搜索完成] 共 {len(results)} 个匹配")
    if incomplete:
        if cancel_reason:
            output_lines.append(
                f"[搜索] 已按停止请求中止扫描：{cancel_reason}；已收集 {len(results)} 个匹配"
                "（结果不完整，建议收窄 pattern 或指定 search_dir）"
            )
        else:
            output_lines.append(
                f"[搜索] 已收集 {len(results)} 个匹配"
                "（结果不完整，已超时截断，建议收窄 pattern 或指定 search_dir）"
            )

    return '\n'.join(output_lines)


def grep_search_tool(
    regex_pattern: str = "",
    include_ext: str = ".py",
    search_dir: str = ".",
    case_sensitive: bool = True,
    max_results: int = None,
    context_lines: Optional[int] = None,
    recursive: bool = True,
    max_output_chars: int = 8000,
    _cancel_checker: Optional[Callable[[], str]] = None,
) -> str:
    """
    全局正则表达式搜索

    主引擎为 ripgrep (rg) 子进程（可杀超时，不阻塞调用线程）；rg 不可用时
    回退纯 Python 扫描（os.walk 分片 deadline）。超时/取消时返回已收集的
    部分结果与显式截断提示，绝不返回裸错误字符串。

    Args:
        regex_pattern: 正则表达式模式
        include_ext: 要搜索的文件扩展名（如 ".py", ".js", "*" 表示所有）
        search_dir: 搜索的根目录；相对路径优先锚定 workspace override，不落到进程 CWD
        case_sensitive: 是否区分大小写
        max_results: 最大返回结果数（默认从配置读取，最高50）
        context_lines: 匹配前后展示的上下文行数；None 表示使用默认配置
        recursive: 兼容参数；当前实现默认递归搜索
        max_output_chars: 最大输出字符数，默认8000，防止上下文爆炸
        _cancel_checker: 由 tool executor 注入的取消检查器；返回非空字符串即中止

    Returns:
        格式化的搜索结果，包含文件路径、行号、匹配行内容
    """
    if max_results is None:
        max_results = _search_defaults.get("MAX_RESULTS", MAX_RESULTS_CONFIG_CAP)
    # 强制上限，防止配置被改大导致上下文爆炸
    max_results = min(int(max_results), MAX_RESULTS_CONFIG_CAP)
    effective_context_lines = MAX_CONTEXT_LINES if context_lines is None else max(0, int(context_lines))

    if not regex_pattern:
        return json.dumps({"status": "error", "code": "EMPTY_PATTERN", "message": "正则表达式不能为空"})
    if _looks_like_redos_pattern(regex_pattern):
        return "[搜索] 错误: 正则表达式存在潜在高复杂度嵌套量词，已拒绝执行"

    search_dir_path = _resolve_search_root(search_dir)

    # 处理文件路径的情况：如果是文件而非目录，直接搜索该文件
    is_single_file = False
    target_filename = None

    if search_dir_path.exists() and search_dir_path.is_file():
        # 用户传入的是文件路径，改为只搜索该文件
        is_single_file = True
        # 先保存文件名，再改变目录路径
        target_filename = search_dir_path.name  # agent.py
        search_dir_path = search_dir_path.parent  # 改为搜索其父目录

    if not search_dir_path.exists():
        return f"[搜索] 错误: 目录不存在 - {search_dir_path}"

    try:
        flags = 0 if case_sensitive else re.IGNORECASE
        pattern = re.compile(regex_pattern, flags)
    except re.error as e:
        return f"[搜索] 错误: 无效的正则表达式 - {e}"

    # 确定要搜索的扩展名
    extensions = _resolve_extensions(include_ext)

    deadline = time.monotonic() + GREP_DEADLINE_SECONDS

    rg_attempt = _grep_via_ripgrep(
        pattern=regex_pattern,
        regex_pattern=regex_pattern,
        search_dir_path=search_dir_path,
        extensions=extensions,
        case_sensitive=case_sensitive,
        effective_context_lines=effective_context_lines,
        target_filename=target_filename,
        max_results=max_results,
        deadline=deadline,
        cancel_checker=_cancel_checker,
    )
    if rg_attempt is not None:
        results, incomplete, cancel_reason = rg_attempt
    else:
        results, incomplete, cancel_reason = _grep_via_python(
            pattern,
            search_dir_path,
            extensions,
            target_filename,
            effective_context_lines,
            max_results,
            deadline,
            _cancel_checker,
        )

    # 格式化输出
    display_dir = f"{search_dir_path}/{target_filename}" if is_single_file else search_dir_path
    return _format_grep_results(
        results,
        regex_pattern,
        display_dir,
        include_ext,
        effective_context_lines,
        max_output_chars,
        incomplete=incomplete,
        cancel_reason=cancel_reason,
    )


def find_function_calls_tool(
    function_name: str,
    search_dir: str = ".",
    include_ext: str = ".py"
) -> str:
    """
    查找特定函数的所有调用位置

    Args:
        function_name: 函数名
        search_dir: 搜索目录
        include_ext: 文件类型

    Returns:
        所有调用位置的列表
    """
    pattern = rf'\b{re.escape(function_name)}\s*\('
    return grep_search_tool(pattern, include_ext, search_dir)


def find_definitions_tool(
    symbol_name: str,
    search_dir: str = ".",
    include_ext: str = ".py"
) -> str:
    """
    查找符号（函数、类、变量）的定义位置

    Args:
        symbol_name: 符号名
        search_dir: 搜索目录
        include_ext: 文件类型

    Returns:
        所有定义位置的列表
    """
    # 匹配 def func_name 或 class ClassName 或 var_name =
    patterns = [
        rf'\bdef\s+{re.escape(symbol_name)}\s*\(',
        rf'\bclass\s+{re.escape(symbol_name)}\s*[\(:]',
        rf'\b{re.escape(symbol_name)}\s*=\s*(?!=)',
    ]
    combined_pattern = '|'.join(patterns)
    return grep_search_tool(combined_pattern, include_ext, search_dir, context_lines=10)


def search_imports_tool(
    module_or_name: str = "",
    module_name: Optional[str] = None,
    search_dir: str = ".",
    include_ext: str = "*"
) -> str:
    """
    查找特定的 import 语句

    Args:
        module_or_name: 模块名或导入的名称
        module_name: 兼容旧调用的别名；若提供则优先使用
        search_dir: 搜索目录
        include_ext: 文件类型

    Returns:
        所有 import 该模块/名称的位置
    """
    # 兼容旧的 positional 调用：search_imports_tool(module_name, search_dir)
    if (
        isinstance(module_name, str)
        and module_name
        and search_dir == "."
        and include_ext == "*"
        and not module_name.startswith(".")
        and ("\\" in module_name or "/" in module_name)
    ):
        search_dir = module_name
        module_name = None

    target = module_name or module_or_name
    if not target:
        return "[搜索] 错误: 模块名不能为空"

    patterns = [
        rf'^import\s+.*{re.escape(target)}',
        rf'^from\s+.*{re.escape(target)}\s+import',
    ]
    combined_pattern = '|'.join(patterns)
    return grep_search_tool(combined_pattern, include_ext, search_dir)


def search_and_read_tool(
    query: str = "",
    search_pattern: Optional[str] = None,
    context_lines: int = 5,
    include_ext: str = ".py",
    search_dir: str = ".",
    max_matches: int = 50,
    max_results: Optional[int] = None
) -> str:
    """
    搜索并读取 - 一步到位的代码检索

    在项目中全局搜索 query，对于每个匹配项，自动携带上下文行返回代码。
    将原来需要 2-3 轮 LLM 交互的操作（grep -> read -> 读取更多上下文）压缩为 1 轮。

    Args:
        query: 搜索关键词（支持正则表达式）
        search_pattern: 兼容旧调用的别名；若提供则优先使用
        context_lines: 每个匹配项返回的上下文行数（前后各 context_lines 行）
        include_ext: 文件类型过滤
        search_dir: 搜索目录
        max_matches: 最大匹配数（超过则截断）
        max_results: 兼容旧调用的别名；若提供则优先使用

    Returns:
        格式化的搜索结果，每个匹配包含完整的上下文代码块
    """
    # 兼容更老的 positional 调用：search_and_read_tool(query, include_ext, search_dir)
    if (
        isinstance(search_pattern, str)
        and search_pattern.startswith(".")
        and isinstance(context_lines, str)
        and include_ext == ".py"
        and search_dir == "."
    ):
        search_dir = context_lines
        include_ext = search_pattern
        search_pattern = None
        context_lines = 5

    # 兼容旧的 positional 调用：search_and_read_tool(query, include_ext, search_dir)
    if isinstance(context_lines, str) and isinstance(include_ext, str) and search_dir == ".":
        search_dir = include_ext
        include_ext = context_lines
        context_lines = 5

    target_query = search_pattern or query
    if not target_query:
        return "[搜索读取] 错误: 查询不能为空"
    effective_max_matches = int(max_results) if max_results is not None else int(max_matches)

    search_dir_path = _normalize_path(search_dir)
    if not search_dir_path.exists():
        return f"[搜索读取] 错误: 目录不存在 - {search_dir_path}"

    # 编译正则
    try:
        pattern = re.compile(target_query)
    except re.error as e:
        return f"[搜索读取] 错误: 无效的正则表达式 - {e}"

    # 确定扩展名
    extensions = _resolve_extensions(include_ext)

    # 收集所有匹配
    all_matches = []
    total_collected_matches = 0

    try:
        for root, dirs, files in os.walk(search_dir_path):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            root_path = Path(root)

            for filename in files:
                file_path = root_path / filename

                if not _should_process_file(file_path):
                    continue
                if file_path.suffix.lower() not in extensions:
                    continue
                if _should_skip_path(file_path):
                    continue

                try:
                    with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                        lines = f.readlines()
                except Exception:
                    continue

                file_matches = []
                for line_num, line in enumerate(lines, 1):
                    if pattern.search(line):
                        # 计算上下文范围
                        start_ctx = max(0, line_num - 1 - context_lines)
                        end_ctx = min(len(lines), line_num + context_lines)

                        # 提取上下文代码块
                        context_block = []
                        for i in range(start_ctx, end_ctx):
                            is_match_line = (i == line_num - 1)
                            marker = ">>>" if is_match_line else "   "
                            context_block.append((i + 1, marker, lines[i].rstrip()))

                        file_matches.append({
                            'line': line_num,
                            'context': context_block,
                            'match_line': line.rstrip(),
                        })
                        total_collected_matches += 1
                        if total_collected_matches >= effective_max_matches:
                            break

                if file_matches:
                    all_matches.append({
                        'file': str(file_path),
                        'matches': file_matches,
                    })

                if total_collected_matches >= effective_max_matches:
                    break

            if total_collected_matches >= effective_max_matches:
                break

    except Exception as e:
        return f"[搜索读取] 错误: 遍历目录时出错 - {e}"

    if not all_matches:
        return (
            f"[搜索读取] 未找到匹配项\n"
            f"查询: {query}\n"
            f"目录: {search_dir_path}\n"
            f"类型: {include_ext}"
        )

    # 格式化输出
    total_matches = sum(len(f['matches']) for f in all_matches)

    output = [
        f"[搜索读取] 查询: {query}",
        f"[搜索读取] 目录: {search_dir_path}",
        f"[搜索读取] 类型: {include_ext}",
        f"[搜索读取] 找到 {total_matches} 处匹配，分布在 {len(all_matches)} 个文件中\n",
        "=" * 80,
    ]

    for file_idx, file_data in enumerate(all_matches, 1):
        output.append(f"\n{'=' * 40}")
        output.append(f"📁 {file_data['file']}")
        output.append(f"{'=' * 40}")

        for match_idx, match in enumerate(file_data['matches'], 1):
            output.append(f"\n--- 匹配 {match_idx} (第 {match['line']} 行) ---")

            # 收集代码块
            code_lines = []
            for line_num, marker, content in match['context']:
                code_lines.append(f"{marker} {line_num:4d} | {content}")

            output.append("```python")
            output.extend(code_lines)
            output.append("```")

    output.append("\n" + "=" * 80)
    output.append(f"[搜索读取完成] 共 {total_matches} 处匹配")

    return '\n'.join(output)
