#!/usr/bin/env python3
"""
Vibelution 一键初始化 / 选择性清理脚本。

清除非核心文件，让 Agent 恢复到初始状态。
所有操作前会显示详情并要求确认，不会静默删除。
"""

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

CATEGORIES = {
    "1": {
        "name": "Agent 工作区",
        "path": ROOT / "workspace",
        "desc": "记忆、技能、提示词、策略、进化历史、SQLite 数据库、对话 transcript",
        "detail": "workspace/ 整个目录",
    },
    "2": {
        "name": "会话日志 (log_info)",
        "path": ROOT / "log_info",
        "desc": "~107 个对话 JSONL 日志文件",
        "detail": "log_info/ 整个目录",
    },
    "3": {
        "name": "运行日志 (logs)",
        "path": ROOT / "logs",
        "desc": "agent_realtime.log, restarter_realtime.log",
        "detail": "logs/ 整个目录",
    },
    "4": {
        "name": "旧备份",
        "path": ROOT / "backups",
        "desc": "10 个旧 agent 备份（zip + py）",
        "detail": "backups/ 整个目录",
    },
    "5": {
        "name": "Python 字节码缓存",
        "path": None,  # 特殊处理：遍历所有 __pycache__
        "desc": "所有 __pycache__/ 目录（约 125 个 .pyc 文件）",
        "detail": "递归查找并删除所有 __pycache__/",
    },
    "6": {
        "name": "Pytest 缓存",
        "path": ROOT / ".pytest_cache",
        "desc": "测试运行缓存",
        "detail": ".pytest_cache/ 整个目录",
    },
    "7": {
        "name": "Claude 会话权限",
        "path": ROOT / ".claude" / "settings.local.json",
        "desc": "累积的 56 条 Bash 权限许可",
        "detail": ".claude/settings.local.json",
    },
    "8": {
        "name": "CodeArtsDoer 快照",
        "path": ROOT / ".codeartsdoer",
        "desc": "规范驱动开发临时文件与原文件快照",
        "detail": ".codeartsdoer/ 整个目录",
    },
    "9": {
        "name": "Arts 编辑器配置",
        "path": ROOT / ".arts",
        "desc": "UI 编辑器模式配置",
        "detail": ".arts/ 整个目录",
    },
}

PRESETS = {
    "deep": {
        "label": "深度清理 — Agent 完全失忆（清除全部 9 项）",
        "keys": {"1", "2", "3", "4", "5", "6", "7", "8", "9"},
    },
    "standard": {
        "label": "标准清理 — 保留开发工具配置（清除 1-7 项）",
        "keys": {"1", "2", "3", "4", "5", "6", "7"},
    },
    "light": {
        "label": "轻度清理 — 仅清记忆+日志（清除 1-4 项）",
        "keys": {"1", "2", "3", "4"},
    },
}


def count_files(p: Path) -> int:
    if p.is_file():
        return 1
    if p.is_dir():
        return sum(1 for _ in p.rglob("*") if _.is_file())
    return 0


def size_fmt(p: Path) -> str:
    if not p.exists():
        return "—"
    if p.is_file():
        total = p.stat().st_size
    else:
        total = sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
    if total < 1024:
        return f"{total} B"
    elif total < 1024 * 1024:
        return f"{total / 1024:.1f} KB"
    else:
        return f"{total / (1024 * 1024):.1f} MB"


def remove_path(p: Path) -> bool:
    try:
        if p.is_file():
            p.unlink()
        elif p.is_dir():
            shutil.rmtree(p, ignore_errors=False)
        return True
    except Exception as e:
        print(f"  [错误] {e}")
        return False


def remove_all_pycache() -> int:
    count = 0
    for d in ROOT.rglob("__pycache__"):
        if d.is_dir() and ".venv" not in d.parts:
            try:
                shutil.rmtree(d)
                count += 1
            except Exception as e:
                print(f"  [错误] {d}: {e}")
    return count


def print_header():
    print()
    print("═" * 60)
    print("  Vibelution 一键初始化 / 选择性清理")
    print("═" * 60)


def show_menu(selected: set[str]):
    print()
    print("  可清除项目：")
    print("  " + "─" * 56)
    for key, cat in CATEGORIES.items():
        mark = "[x]" if key in selected else "[ ]"
        exists = cat["path"].exists() if cat["path"] else any(ROOT.rglob("__pycache__"))
        status = f"({size_fmt(cat['path'])})" if cat["path"] else "(递归查找)"
        if not exists and cat["path"]:
            status = "(不存在)"
        print(f"  {mark} {key}. {cat['name']:20s} {status}")
        print(f"       {cat['desc']}")
    print("  " + "─" * 56)
    print()


def show_presets():
    print()
    print("  预设方案：")
    for key, preset in PRESETS.items():
        print(f"  [{key}] {preset['label']}")


def confirm(selected: set[str]) -> bool:
    print()
    print("  ⚠ 即将清除以下项目：")
    for key in sorted(selected, key=int):
        cat = CATEGORIES[key]
        print(f"    - {cat['name']}: {cat['detail']}")
    print()
    resp = input("  确认执行？(yes/no): ").strip().lower()
    return resp in ("yes", "y")


def execute(selected: set[str]):
    print()
    print("  开始清理...")
    print()

    success = 0
    fail = 0

    for key in sorted(selected, key=int):
        cat = CATEGORIES[key]
        print(f"  [{cat['name']}] ", end="")

        if key == "5":
            n = remove_all_pycache()
            if n > 0:
                print(f"已删除 {n} 个 __pycache__/ 目录")
                success += 1
            else:
                print("未找到 __pycache__/")
                success += 1
        else:
            p = cat["path"]
            if not p.exists():
                print("不存在，跳过")
                success += 1
                continue
            if remove_path(p):
                print("已清除")
                success += 1
            else:
                fail += 1

    print()
    print(f"  完成: {success} 项成功, {fail} 项失败")


def interactive():
    selected: set[str] = set()

    while True:
        print_header()
        show_presets()
        show_menu(selected)

        if selected:
            shown = ", ".join(sorted(selected, key=int))
            print(f"  当前选中: {shown}")
        else:
            print("  当前选中: (无)")

        print()
        cmd = input("  输入数字切换 / 预设名(deep/standard/light) / go 执行 / q 退出: ").strip().lower()

        if cmd == "q":
            print("  已取消。")
            sys.exit(0)

        if cmd == "go":
            if not selected:
                print("  未选中任何项目。")
                continue
            if confirm(selected):
                execute(selected)
                print()
                print("  清理完成。")
                sys.exit(0)
            else:
                print("  已取消执行。")
                continue

        if cmd in PRESETS:
            selected = set(PRESETS[cmd]["keys"])
            continue

        # toggle single item
        if cmd in CATEGORIES:
            if cmd in selected:
                selected.discard(cmd)
            else:
                selected.add(cmd)
            continue

        # toggle multiple: "123"
        if cmd.isdigit() and all(c in CATEGORIES for c in cmd):
            for c in cmd:
                if c in selected:
                    selected.discard(c)
                else:
                    selected.add(c)
            continue

        print(f"  无效输入: {cmd}")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Vibelution 一键初始化工具")
    parser.add_argument(
        "--preset",
        choices=["deep", "standard", "light"],
        help="使用预设方案（跳过交互菜单）",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="跳过确认（仅 --preset 时有效）",
    )
    args = parser.parse_args()

    if args.preset:
        selected = PRESETS[args.preset]["keys"]
        print_header()
        print(f"\n  预设: {PRESETS[args.preset]['label']}")
        if not args.yes:
            if not confirm(selected):
                print("  已取消。")
                sys.exit(0)
        execute(selected)
        print()
        print("  清理完成。")
    else:
        interactive()


if __name__ == "__main__":
    main()
