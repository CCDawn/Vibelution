"""One-shot generator for core/web/services/README.md (agent index)."""
from __future__ import annotations

import ast
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SVC = ROOT / "core" / "web" / "services"
ROUTES = ROOT / "core" / "web" / "routes"
TESTS = ROOT / "tests"


def one_line(path: Path) -> str:
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    text = raw.decode("utf-8", errors="replace")
    try:
        doc = ast.get_docstring(ast.parse(text)) or ""
    except SyntaxError:
        doc = ""
    doc = doc.strip()
    if doc:
        line = re.sub(r"\s+", " ", doc.split("\n\n")[0].split("\n")[0]).strip()
        return (line[:120] + "...") if len(line) > 120 else line
    if "user_content" in path.name:
        return "User markdown content space (read/index/delete semantics for workbench)."
    for line in text.splitlines()[:40]:
        s = line.strip()
        if s.startswith("#") and len(s) > 4:
            return s.lstrip("#").strip()[:120]
    return "(no docstring — read module header)"


def domain(stem: str) -> str:
    order = [
        ("session_service", "session"),
        ("team_workflow", "team_workflow"),
        ("team_knowledge", "knowledge"),
        ("team_", "team"),
        ("agent_directory", "agent"),
        ("agent_", "agent"),
        ("cli_agent", "cli_agent"),
        ("project_agent_bus", "agent"),
        ("prompt_template", "agent"),
        ("supervised_agent", "evolution"),
        ("chat_room", "chat"),
        ("conversation", "chat"),
        ("rag_", "knowledge"),
        ("unified_knowledge", "knowledge"),
        ("github_project_library", "memory"),
        ("memory_", "memory"),
        ("research_", "research"),
        ("challenge_cup", "research"),
        ("self_evolution", "evolution"),
        ("supervised_", "evolution"),
        ("evolution_", "evolution"),
        ("chat_review", "evolution"),
        ("runtime_scene", "runtime"),
        ("runtime_", "runtime"),
        ("launcher", "launcher"),
        ("reset", "launcher"),
        ("config", "config"),
        ("provider_", "config"),
        ("model_", "config"),
        ("theme_", "config"),
        ("avatar_", "config"),
        ("tool_policy", "config"),
        ("workbench_", "workbench"),
        ("git_", "git"),
        ("log_", "ops"),
        ("diagnostics", "ops"),
        ("file_", "workspace"),
        ("pet_", "pet"),
        ("skill_", "skills"),
        ("tool_registry", "tools"),
        ("computer_use", "computer_use"),
        ("data_processing", "data"),
        ("user_content", "content"),
    ]
    for pref, d in order:
        if stem == pref or stem.startswith(pref) or pref in stem:
            return d
    return "other"


DOMAIN_TITLES = {
    "session": "Session / Chat hot path",
    "team_workflow": "Team workflow / SC / experiment",
    "team": "Team registry / canvas",
    "agent": "Agent directory / config",
    "cli_agent": "CLI Agent",
    "chat": "Chat room / conversation index",
    "knowledge": "Knowledge / RAG",
    "memory": "Memory",
    "research": "Research / Challenge Cup",
    "evolution": "Self / Supervised evolution",
    "runtime": "Runtime / runtime scene",
    "launcher": "Launcher / Reset",
    "config": "Config / Provider / Model / Theme",
    "workbench": "Workbench contract / preferences",
    "git": "Git",
    "ops": "Logs / Diagnostics",
    "workspace": "Workspace files",
    "tools": "Tools registry",
    "skills": "Skills",
    "pet": "Pet",
    "computer_use": "Computer Use",
    "data": "Data processing",
    "content": "User content markdown",
    "other": "Other",
}

DOM_ORDER = [
    "session",
    "team_workflow",
    "team",
    "agent",
    "cli_agent",
    "chat",
    "knowledge",
    "memory",
    "research",
    "evolution",
    "runtime",
    "launcher",
    "config",
    "workbench",
    "git",
    "ops",
    "workspace",
    "tools",
    "skills",
    "pet",
    "computer_use",
    "data",
    "content",
    "other",
]

PACK_MAP = {
    "session_service": "session/",
    "team_workflow_orchestration_service": "team_workflow/",
    "team_service": "team/",
    "team_knowledge_service": "team_knowledge/",
    "agent_directory_service": "agent_directory/",
    "runtime_scene_service": "runtime_scene/",
}


def main() -> None:
    facades = sorted(SVC.glob("*_service.py"))
    route_hits: dict[str, set[str]] = {p.stem: set() for p in facades}

    for rp in ROUTES.rglob("*.py"):
        text = rp.read_text(encoding="utf-8", errors="replace")
        rel = str(rp.relative_to(ROOT / "core" / "web")).replace("\\", "/")
        for m in re.finditer(
            r"from core\.web\.services(?:\.[\w]+)? import \(?([^)\n]+)", text
        ):
            for part in re.split(r"[,\s]+", m.group(1)):
                part = part.strip().strip("()")
                if part in route_hits:
                    route_hits[part].add(rel)
        for m in re.finditer(r"core\.web\.services\.(\w+_service)", text):
            if m.group(1) in route_hits:
                route_hits[m.group(1)].add(rel)
        for stem in route_hits:
            if re.search(rf"(?:import|from)[^\n]*\b{stem}\b", text) and "services" in text:
                route_hits[stem].add(rel)

    test_files = list(TESTS.glob("test_*.py"))
    test_hits: dict[str, list[str]] = {}
    for p in facades:
        stem = p.stem
        base = stem.replace("_service", "")
        content: list[str] = []
        nameonly: list[str] = []
        for tp in test_files:
            t = tp.read_text(encoding="utf-8", errors="replace")
            if stem in t:
                content.append(tp.name)
            elif base in tp.stem:
                nameonly.append(tp.name)
        test_hits[stem] = content[:3] or nameonly[:2]

    rows = []
    for p in facades:
        stem = p.stem
        routes = sorted(
            {
                r.replace("\\", "/").replace("routes/", "")
                for r in route_hits.get(stem, set())
            }
        )[:5]
        rows.append(
            {
                "file": p.name,
                "stem": stem,
                "doc": one_line(p),
                "pack": PACK_MAP.get(stem, ""),
                "routes": routes,
                "tests": test_hits.get(stem, []),
                "domain": domain(stem),
            }
        )

    by: dict[str, list] = defaultdict(list)
    for r in rows:
        by[r["domain"]].append(r)

    lines: list[str] = []
    lines.append("# `core/web/services` — Agent 全量索引")
    lines.append("")
    lines.append("> **读者：coding Agent。** 写入前用本表定位 facade / pack。")
    lines.append(
        "> 规则：`docs/standards/development-standard.md` §8.3 / §24；"
        "总图：`docs/guides/ownership.md`。"
    )
    lines.append(
        "> 数据：模块 docstring + routes 引用扫描 + tests 引用（启发式，非穷尽）。"
    )
    lines.append("> 验证以代码 import 与 `tests/select_tests.py` 为准。")
    lines.append("")
    lines.append("## 用法")
    lines.append("")
    lines.append("```text")
    lines.append("1. 关键词 / facade 名 → 下方 Domain 表")
    lines.append("2. Pack 非空 → 先读 Pack/README.md；改 pack 不堆 facade")
    lines.append("3. Pack 空 → 改该 *_service.py；复杂逻辑再拆 pack")
    lines.append("4. Routes → core/web/routes/<path>")
    lines.append("5. Tests → tests/<file>；空则 select_tests.py")
    lines.append("```")
    lines.append("")
    lines.append("## Pack 域（有独立 README）")
    lines.append("")
    lines.append("| Pack | Facade | README |")
    lines.append("| --- | --- | --- |")
    lines.append(
        "| `session/` | `session_service.py` | [session/README.md](session/README.md) |"
    )
    lines.append(
        "| `team_workflow/` | `team_workflow_orchestration_service.py` | "
        "[team_workflow/README.md](team_workflow/README.md) |"
    )
    lines.append("| `team/` | `team_service.py` | [team/README.md](team/README.md) |")
    lines.append(
        "| `team_knowledge/` | `team_knowledge_service.py` | "
        "[team_knowledge/README.md](team_knowledge/README.md) |"
    )
    lines.append(
        "| `agent_directory/` | `agent_directory_service.py` | "
        "[agent_directory/README.md](agent_directory/README.md) |"
    )
    lines.append(
        "| `runtime_scene/` | `runtime_scene_service.py` | "
        "[runtime_scene/README.md](runtime_scene/README.md) |"
    )
    lines.append("")
    lines.append("## 统计")
    lines.append("")
    lines.append(f"- Facade `*_service.py`：**{len(rows)}**")
    lines.append("- 有 pack README：**6**")
    lines.append(f"- 仅单文件 facade：**{len(rows) - 6}**")
    lines.append("")
    lines.append("## Domain 速查")
    lines.append("")
    lines.append("| Domain | Facades |")
    lines.append("| --- | ---: |")
    for d in DOM_ORDER:
        if d in by:
            lines.append(f"| {DOMAIN_TITLES.get(d, d)} (`{d}`) | {len(by[d])} |")
    lines.append("")

    for d in DOM_ORDER:
        if d not in by:
            continue
        lines.append(f"## {DOMAIN_TITLES.get(d, d)}")
        lines.append("")
        lines.append(
            "| Facade | 职责（docstring） | Pack | Routes（主） | Tests（启发式） |"
        )
        lines.append("| --- | --- | --- | --- | --- |")
        for r in by[d]:
            pack = f"`{r['pack']}`" if r["pack"] else "—"
            routes = (
                ", ".join(f"`{x}`" for x in r["routes"]) if r["routes"] else "—"
            )
            tests = (
                ", ".join(f"`{x}`" for x in r["tests"]) if r["tests"] else "—"
            )
            doc = r["doc"].replace("|", "\\|")
            lines.append(
                f"| `{r['file']}` | {doc} | {pack} | {routes} | {tests} |"
            )
        lines.append("")

    lines.append("## 硬边界（所有 facade）")
    lines.append("")
    lines.append("| MUST | MUST NOT |")
    lines.append("| --- | --- |")
    lines.append("| Route 薄；业务在 service/pack | Route 直写 store / 无界业务 |")
    lines.append("| 有 pack 时新逻辑进 pack + re-export | 只在 facade 无限堆实现 |")
    lines.append("| 公共 JSON 有 `response_model` | 无故升高 untyped endpoint 预算 |")
    lines.append("| Projection 只读派生 | Projection 第二写入 |")
    lines.append("| 改后聚焦测试 | 无验证声称完成 |")
    lines.append("")
    lines.append("## 维护")
    lines.append("")
    lines.append("- 新增 `*_service.py`：同一 PR 更新本表一行（或重跑生成脚本）。")
    lines.append("- 拆 pack：填 Pack 列并添加 `README.md`（30 秒 routing 表）。")
    lines.append("- Docstring 第一句 = 一句话职责（本索引依赖）。")
    lines.append("- 重生成：`python scripts/_gen_services_readme.py`")
    lines.append("")

    out = SVC / "README.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"WROTE {out} services={len(rows)} lines={len(lines)}")


if __name__ == "__main__":
    main()
