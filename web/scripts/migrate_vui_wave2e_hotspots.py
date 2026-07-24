#!/usr/bin/env python3
"""Wave 2E: compress high-frequency residual color-mix onto structure/state recipes.

Targets Research / ResearchFlow / Tools / Teams / ConversationView and related
hotspots. Safe fragment replaces only; does not collapse whitespace.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
RECIPES = "design/vuiSurfaceRecipes"

# Files to process (relative to web/src). Empty = all *.styles.ts with hits.
TARGET_GLOBS = [
    "routes/ResearchRoute.styles.ts",
    "routes/ResearchFlowCanvasRoute.styles.ts",
    "routes/ToolsRoute.styles.ts",
    "routes/TeamsRoute.styles.ts",
    "routes/EvolutionRoute.styles.ts",
    "routes/ConfigRoute.styles.ts",
    "routes/ChatCodingRoute.styles.ts",
    "routes/LogsRoute.styles.ts",
    "routes/GitRoute.styles.ts",
    "routes/AgentsRoute.styles.ts",
    "routes/SelfEvolutionTrack.styles.ts",
    "routes/EvolutionActiveRunMonitorPanel.styles.ts",
    "routes/LauncherRoute.styles.ts",
    "routes/AgentCreatePanel.styles.ts",
    "routes/AgentOverviewPanel.styles.ts",
    "routes/UsageRoute.styles.ts",
    "routes/SkillsRoute.styles.ts",
    "routes/PromptTemplatesRoute.styles.ts",
    "routes/SupervisedReviewRoute.styles.ts",
    "components/conversation/ConversationView.styles.ts",
]

# Longest first. Values are recipe symbol names.
REPLACEMENTS: list[tuple[str, str]] = [
    # Structural opaque panels with soft-border mix (common Research/Tools pattern)
    (
        "rounded-[var(--radius-panel)] border border-[color:color-mix(in_srgb,var(--border-soft)_72%,transparent)] !bg-[var(--vui-surface-panel)]",
        "vuiOpaquePanelClass",
    ),
    (
        "rounded-[var(--radius-panel)] border border-[color:color-mix(in_srgb,var(--border-soft)_70%,transparent)] !bg-[var(--vui-surface-panel)]",
        "vuiOpaquePanelClass",
    ),
    (
        "rounded-[var(--radius-panel)] border border-[color:color-mix(in_srgb,var(--border-soft)_68%,transparent)] !bg-[var(--vui-surface-panel)]",
        "vuiOpaquePanelClass",
    ),
    (
        "rounded-[var(--radius-panel)] border border-[color:color-mix(in_srgb,var(--border-soft)_58%,transparent)] !bg-[var(--vui-surface-panel)]",
        "vuiOpaquePanelClass",
    ),
    (
        "rounded-[var(--radius-control)] border border-[color:color-mix(in_srgb,var(--border-soft)_72%,transparent)] !bg-[var(--vui-surface-panel)]",
        "vuiOpaqueRowClass",
    ),
    (
        "rounded-[var(--radius-control)] border border-[color:color-mix(in_srgb,var(--border-soft)_68%,transparent)] !bg-[var(--vui-surface-panel)]",
        "vuiOpaqueRowClass",
    ),
    (
        "rounded-[var(--radius-control)] border border-[color:color-mix(in_srgb,var(--border-soft)_62%,transparent)] !bg-[var(--vui-surface-row)]",
        "vuiOpaqueRowClass",
    ),
    (
        "rounded-[var(--radius-control)] border border-[color:color-mix(in_srgb,var(--border-soft)_58%,transparent)] !bg-[var(--vui-surface-row)]",
        "vuiOpaqueRowClass",
    ),
    (
        "rounded-[var(--radius-control)] border border-[color:color-mix(in_srgb,var(--vui-border-subtle)_58%,transparent)] !bg-[var(--vui-surface-row)]",
        "vuiOpaqueRowClass",
    ),
    # Cool soft panels (near cool-info / cool-soft)
    (
        "border border-[color:color-mix(in_srgb,var(--accent-cool)_28%,transparent)] bg-[color:color-mix(in_srgb,var(--accent-cool)_7%,transparent)]",
        "vuiStateCoolInfoClass",
    ),
    (
        "border border-[color:color-mix(in_srgb,var(--accent-cool)_28%,transparent)] bg-[color:color-mix(in_srgb,var(--accent-cool)_6%,transparent)]",
        "vuiStateCoolInfoClass",
    ),
    (
        "border border-[color:color-mix(in_srgb,var(--accent-cool)_28%,transparent)] bg-[color:color-mix(in_srgb,var(--accent-cool)_8%,transparent)]",
        "vuiStateCoolInfoClass",
    ),
    (
        "border border-[color:color-mix(in_srgb,var(--accent-cool)_30%,transparent)] bg-[color:color-mix(in_srgb,var(--accent-cool)_8%,transparent)]",
        "vuiStateCoolInfoClass",
    ),
    (
        "border border-[color:color-mix(in_srgb,var(--accent-cool)_34%,transparent)] bg-[color:color-mix(in_srgb,var(--accent-cool)_10%,transparent)]",
        "vuiStateCoolSoftClass",
    ),
    # Standard state soft chips (tailwind form without color:)
    (
        "border-[color-mix(in_srgb,var(--state-warning)_36%,transparent)] bg-[color-mix(in_srgb,var(--state-warning)_10%,transparent)] text-[var(--state-warning)]",
        "vuiStateWarningSoftClass",
    ),
    (
        "border-[color-mix(in_srgb,var(--state-success)_32%,transparent)] bg-[color-mix(in_srgb,var(--state-success)_9%,transparent)] text-[var(--state-success)]",
        "vuiStateSuccessSoftClass",
    ),
    (
        "border-[color-mix(in_srgb,var(--state-success)_28%,transparent)] bg-[color-mix(in_srgb,var(--state-success)_9%,transparent)] text-[var(--state-success)]",
        "vuiStateSuccessSoftClass",
    ),
    (
        "border-[color-mix(in_srgb,var(--accent-warm)_24%,transparent)] bg-[color-mix(in_srgb,var(--accent-warm)_8%,transparent)] text-[var(--accent-warm)]",
        "vuiStateWarmSoftClass",
    ),
    (
        "border-[color-mix(in_srgb,var(--state-error)_36%,transparent)] bg-[color-mix(in_srgb,var(--state-error)_9%,transparent)] text-[var(--state-error)]",
        "vuiStateDangerSoftClass",
    ),
    # Arbitrary color: form of state chips
    (
        "border border-[color:color-mix(in_srgb,var(--state-error)_36%,transparent)] bg-[color:color-mix(in_srgb,var(--state-error)_9%,transparent)]",
        "vuiStateDangerSoftClass",
    ),
    (
        "border border-[color:color-mix(in_srgb,var(--state-success)_32%,transparent)] bg-[color:color-mix(in_srgb,var(--state-success)_9%,transparent)]",
        "vuiStateSuccessSoftClass",
    ),
    (
        "border border-[color:color-mix(in_srgb,var(--state-warning)_36%,transparent)] bg-[color:color-mix(in_srgb,var(--state-warning)_10%,transparent)]",
        "vuiStateWarningSoftClass",
    ),
    # Selected fill (remaining bare fills)
    (
        "bg-[color-mix(in_srgb,var(--accent-cool)_10%,var(--vui-surface-row))]",
        "vuiStateSelectedRowFillClass",
    ),
    (
        "[background:color-mix(in_srgb,_var(--accent-cool)_10%,_var(--vui-surface-row))]",
        "vuiStateSelectedRowFillClass",
    ),
    (
        "[background:color-mix(in_srgb,var(--accent-cool)_10%,var(--vui-surface-row))]",
        "vuiStateSelectedRowFillClass",
    ),
    # Underscore arbitrary-property form (Agents / legacy CSS-module ports)
    (
        "[background:color-mix(in_srgb,_var(--accent-cool)_10%,_var(--vui-surface-row))]",
        "vuiStateSelectedRowFillClass",
    ),
    (
        "[background:color-mix(in_srgb,_var(--accent-cool)_5%,_var(--vui-surface-row))]",
        "vuiStateSelectedRowFillClass",
    ),
    (
        "[background:color-mix(in_srgb,_var(--state-success)_5%,_var(--vui-surface-row))]",
        "vuiStateSuccessSoftClass",
    ),
    (
        "[background:color-mix(in_srgb,_var(--accent-warm)_5%,_var(--vui-surface-row))]",
        "vuiStateSelectedWarmRowClass",
    ),
    (
        "[background:color-mix(in_srgb,_var(--accent-cool)_6%,_var(--vui-surface-panel))]",
        "vuiStateAccentBannerClass",
    ),
    (
        "[background:color-mix(in_srgb,_var(--accent-cool)_8%,_var(--vui-surface-panel))]",
        "vuiStateAccentBannerClass",
    ),
]

IMPORT_RE = re.compile(
    r'import\s*\{([^}]*)\}\s*from\s*["\']([^"\']*vuiSurfaceRecipes)["\']\s*;',
    re.M,
)


def rel_import(file: Path) -> str:
    depth = len(file.relative_to(ROOT).parts) - 1
    if depth <= 0:
        return f"./{RECIPES}"
    return "../" * depth + RECIPES


def ensure_import(source: str, file: Path, symbols: set[str]) -> str:
    if not symbols:
        return source
    m = IMPORT_RE.search(source)
    if m:
        existing = {s.strip() for s in m.group(1).split(",") if s.strip()}
        merged = sorted(existing | symbols)
        new_block = "import {\n  " + ",\n  ".join(merged) + f',\n}} from "{m.group(2)}";'
        return source[: m.start()] + new_block + source[m.end() :]
    import_line = (
        "import {\n  " + ",\n  ".join(sorted(symbols)) + f',\n}} from "{rel_import(file)}";\n'
    )
    last_import = None
    for im in re.finditer(r"^import\s.+?;\s*$", source, re.M):
        last_import = im
    if last_import:
        i = last_import.end()
        return source[:i] + "\n" + import_line + source[i:]
    m2 = re.match(r"(^(?://.*\n|/\*[\s\S]*?\*/\n)*)", source)
    if m2:
        return source[: m2.end()] + import_line + "\n" + source[m2.end() :]
    return import_line + "\n" + source


def quote_context_at(source: str, index: int) -> str:
    in_template = False
    in_double = False
    in_single = False
    i = 0
    while i < index:
        ch = source[i]
        if in_template:
            if ch == "\\":
                i += 2
                continue
            if ch == "`":
                in_template = False
            elif ch == "$" and i + 1 < len(source) and source[i + 1] == "{":
                depth = 0
                j = i + 1
                while j < index:
                    if source[j] == "{":
                        depth += 1
                    elif source[j] == "}":
                        depth -= 1
                        if depth == 0:
                            i = j + 1
                            break
                    j += 1
                else:
                    return "template"
                continue
            i += 1
            continue
        if in_double:
            if ch == "\\":
                i += 2
                continue
            if ch == '"':
                in_double = False
            i += 1
            continue
        if in_single:
            if ch == "\\":
                i += 2
                continue
            if ch == "'":
                in_single = False
            i += 1
            continue
        if ch == "`":
            in_template = True
        elif ch == '"':
            in_double = True
        elif ch == "'":
            in_single = True
        i += 1
    if in_template:
        return "template"
    if in_double:
        return "double"
    if in_single:
        return "single"
    return "none"


def find_string_bounds(source: str, index: int, kind: str) -> tuple[int, int] | None:
    if kind == "template":
        q = "`"
    elif kind == "double":
        q = '"'
    elif kind == "single":
        q = "'"
    else:
        return None
    i = index - 1
    open_i = None
    while i >= 0:
        if source[i] == q:
            bs = 0
            j = i - 1
            while j >= 0 and source[j] == "\\":
                bs += 1
                j -= 1
            if bs % 2 == 1:
                i -= 1
                continue
            open_i = i
            break
        i -= 1
    if open_i is None:
        return None
    i = open_i + 1
    while i < len(source):
        ch = source[i]
        if ch == "\\":
            i += 2
            continue
        if kind == "template" and ch == "$" and i + 1 < len(source) and source[i + 1] == "{":
            depth = 0
            j = i + 1
            while j < len(source):
                if source[j] == "{":
                    depth += 1
                elif source[j] == "}":
                    depth -= 1
                    if depth == 0:
                        i = j + 1
                        break
                j += 1
            else:
                return None
            continue
        if ch == q:
            return open_i, i
        i += 1
    return None


def apply_replacements(source: str) -> tuple[str, set[str]]:
    used: set[str] = set()
    for frag, symbol in REPLACEMENTS:
        while True:
            idx = source.find(frag)
            if idx < 0:
                break
            kind = quote_context_at(source, idx)
            bounds = find_string_bounds(source, idx, kind)
            if bounds is None:
                source = source[:idx] + source[idx + 1 :]
                continue
            open_i, close_i = bounds
            body_start = open_i + 1
            body_end = close_i
            body = source[body_start:body_end]
            rel = idx - body_start
            new_body = body[:rel] + f"${{{symbol}}}" + body[rel + len(frag) :]
            if kind == "template":
                source = source[:body_start] + new_body + source[body_end:]
            elif kind in ("double", "single"):
                source = source[:open_i] + "`" + new_body + "`" + source[close_i + 1 :]
            else:
                source = source[:idx] + f"${{{symbol}}}" + source[idx + len(frag) :]
            used.add(symbol)
    return source, used


def apply_file(path: Path) -> bool:
    if path.name == "vuiSurfaceRecipes.ts":
        return False
    original = path.read_text(encoding="utf-8")
    source, used = apply_replacements(original)
    if not used:
        return False
    source = ensure_import(source, path, used)
    if source != original:
        path.write_text(source, encoding="utf-8", newline="\n")
        return True
    return False


def main() -> None:
    changed: list[str] = []
    for rel in TARGET_GLOBS:
        path = ROOT / rel
        if not path.exists():
            print("missing", rel)
            continue
        if apply_file(path):
            changed.append(rel)
    print(f"updated {len(changed)} files")
    for p in changed:
        print(" ", p)


if __name__ == "__main__":
    main()
