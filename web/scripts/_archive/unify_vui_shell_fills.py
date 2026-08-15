#!/usr/bin/env python3
"""Add workspace/rail fills to major route shells missing backgrounds."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"

# path relative to web/src -> list of (key, fill_symbol)
# only apply if key value doesn't already contain fill/bg-vui-surface
TARGETS: dict[str, list[tuple[str, str]]] = {
    "routes/AgentInspectorRailPanel.styles.ts": [("rail", "vuiRailFillClass")],
    "routes/ResearchFlowCanvasRoute.styles.ts": [
        ("inspector", "vuiRailFillClass"),
        ("route", "vuiWorkspaceFillClass"),
    ],
    "routes/ResearchRoute.styles.ts": [
        ("route", "vuiWorkspaceFillClass"),
        ("workspace", "vuiWorkspaceFillClass"),
    ],
    "routes/MemoryRoute.styles.ts": [
        ("route", "vuiWorkspaceFillClass"),
        ("workspace", "vuiWorkspaceFillClass"),
    ],
    "routes/LogsRoute.styles.ts": [
        ("route", "vuiWorkspaceFillClass"),
        ("workspace", "vuiWorkspaceFillClass"),
        ("sidebar", "vuiRailFillClass"),
    ],
    "routes/ToolsRoute.styles.ts": [
        ("route", "vuiWorkspaceFillClass"),
        ("workspace", "vuiWorkspaceFillClass"),
    ],
    "routes/GitRoute.styles.ts": [
        ("route", "vuiWorkspaceFillClass"),
        ("workspace", "vuiWorkspaceFillClass"),
    ],
    "routes/LauncherRoute.styles.ts": [
        ("route", "vuiWorkspaceFillClass"),
        ("workspace", "vuiWorkspaceFillClass"),
    ],
    "routes/SupervisedReviewRoute.styles.ts": [
        ("workspace", "vuiWorkspaceFillClass"),
    ],
    "routes/AgentsRoute.styles.ts": [
        ("route", "vuiWorkspaceFillClass"),
    ],
    "routes/ConfigRoute.styles.ts": [
        # sidebar already uses readablePanelSurface
    ],
    "routes/MemoryAgentMemoryPanel.styles.ts": [("workspace", "vuiWorkspaceFillClass")],
    "routes/MemoryGraphViewPanel.styles.ts": [("workspace", "vuiWorkspaceFillClass")],
    "routes/MemoryManagePanel.styles.ts": [("workspace", "vuiWorkspaceFillClass")],
    "routes/ConfigSettingsNavigation.styles.ts": [("sidebar", "vuiRailFillClass")],
    "routes/ConfigQuickSetupPanel.styles.ts": [("workspace", "vuiWorkspaceFillClass")],
    "routes/RuntimeScenesPane.styles.ts": [("sidebar", "vuiRailFillClass")],
}

IMPORT_RE = re.compile(
    r'import\s*\{([^}]*)\}\s*from\s*["\']([^"\']*vuiSurfaceRecipes)["\']\s*;',
    re.M,
)
HAS_BG_RE = re.compile(
    r"bg-vui-surface|!bg-vui|bg-\[var\(--vui-surface|!bg-\[var\(--vui-surface|"
    r"vuiRailFill|vuiWorkspaceFill|vuiChatFill|vuiOpaque|vuiFlat|vuiElevated|readablePanelSurface"
)


def rel_import(file: Path) -> str:
    depth = len(file.relative_to(ROOT).parts) - 1
    return ("../" * depth if depth else "./") + "design/vuiSurfaceRecipes"


def ensure_import(source: str, file: Path, symbols: set[str]) -> str:
    if not symbols:
        return source
    m = IMPORT_RE.search(source)
    if m:
        existing = {s.strip() for s in m.group(1).split(",") if s.strip()}
        merged = sorted(existing | symbols)
        block = "import {\n  " + ",\n  ".join(merged) + f',\n}} from "{m.group(2)}";'
        return source[: m.start()] + block + source[m.end() :]
    line = "import {\n  " + ",\n  ".join(sorted(symbols)) + f',\n}} from "{rel_import(file)}";\n'
    last = None
    for im in re.finditer(r"^import\s.+?;\s*$", source, re.M):
        last = im
    if last:
        return source[: last.end()] + "\n" + line + source[last.end() :]
    m2 = re.match(r"(^(?://.*\n|/\*[\s\S]*?\*/\n)*)", source)
    if m2:
        return source[: m2.end()] + line + "\n" + source[m2.end() :]
    return line + "\n" + source


def patch_key(source: str, key: str, symbol: str) -> tuple[str, bool]:
    # match key: "..." or key: `...`
    pat = re.compile(
        rf"(^\s*{re.escape(key)}\s*:\s*)([`\"])(.+?)(\2)",
        re.M | re.S,
    )
    m = pat.search(source)
    if not m:
        return source, False
    quote, body = m.group(2), m.group(3)
    if HAS_BG_RE.search(body) or f"${{{symbol}}}" in body or symbol in body:
        return source, False
    if quote == "`":
        new_body = f"{body} ${{{symbol}}}" if not body.endswith(" ") else f"{body}${{{symbol}}}"
        # ensure space before ${
        if not body.endswith(" "):
            new_body = body + f" ${{{symbol}}}"
        else:
            new_body = body + f"${{{symbol}}}"
        replacement = f"{m.group(1)}`{new_body}`"
    else:
        # promote to template
        new_body = body + f" ${{{symbol}}}"
        replacement = f"{m.group(1)}`{new_body}`"
    return source[: m.start()] + replacement + source[m.end() :], True


def main() -> None:
    changed = []
    for rel, keys in TARGETS.items():
        if not keys:
            continue
        path = ROOT / rel
        if not path.exists():
            print("missing", rel)
            continue
        src = path.read_text(encoding="utf-8")
        used: set[str] = set()
        orig = src
        for key, symbol in keys:
            src, ok = patch_key(src, key, symbol)
            if ok:
                used.add(symbol)
        if used:
            src = ensure_import(src, path, used)
        if src != orig:
            path.write_text(src, encoding="utf-8", newline="\n")
            changed.append(rel)
            print("updated", rel, sorted(used))
    print("files", len(changed))


if __name__ == "__main__":
    main()
