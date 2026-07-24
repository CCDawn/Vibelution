"""Pass 2: flexible recipe splice for collapsed !bg surfaces + glass panels."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"

ROW_FLEX = re.compile(
    r"rounded-\[var\(--radius-control\)\]\s+border\s+border-\[[^\]]+\]\s+"
    r"(?:!)?bg-\[var\(--vui-surface-row\)\]"
)
PANEL_FLEX = re.compile(
    r"rounded-\[var\(--radius-panel\)\]\s+border\s+border-\[[^\]]+\]\s+"
    r"(?:!)?bg-\[var\(--vui-surface-panel\)\]"
)
GLASS_FLEX = re.compile(
    r"rounded-\[var\(--radius-panel\)\]\s+border\s+border-\[[^\]]+\]\s+"
    r"bg-\[var\(--vui-surface-glass\)\]"
    r"(?:\s+shadow-\[[^\]]+\])?"
)
# Arbitrary agents-style with !bg after structural collapse
ROW_ARB_FLEX = re.compile(
    r"\[border:1px_solid[^\]]*\]\s+\[border-radius:var\(--radius-control\)\]\s+"
    r"(?:!bg-\[var\(--vui-surface-row\)\]|\[background:var\(--vui-surface-row\)\])"
)
PANEL_ARB_FLEX = re.compile(
    r"\[border:1px_solid[^\]]*\]\s+\[border-radius:var\(--radius-panel\)\]\s+"
    r"(?:!bg-\[var\(--vui-surface-panel\)\]|\[background:var\(--vui-surface-panel\)\])"
)


def import_path_for(file: Path) -> str:
    rel = file.relative_to(ROOT)
    depth = len(rel.parts) - 1
    return ("../" * depth) + "design/vuiSurfaceRecipes"


def ensure_import(text: str, file: Path, symbols: set[str]) -> str:
    if not symbols:
        return text
    if "vuiSurfaceRecipes" not in text:
        imp = (
            "import {\n  "
            + ",\n  ".join(sorted(symbols))
            + f',\n}} from "{import_path_for(file)}";\n\n'
        )
        lines = text.splitlines(keepends=True)
        i = 0
        while i < len(lines):
            s = lines[i].lstrip()
            if (
                s.startswith("//")
                or s.startswith("/*")
                or s.startswith("*")
                or s.strip() == ""
            ):
                i += 1
                continue
            break
        return "".join(lines[:i]) + imp + "".join(lines[i:])

    m = re.search(
        r"import\s*\{([^}]+)\}\s*from\s*[\"'][^\"']*vuiSurfaceRecipes[\"']\s*;",
        text,
    )
    if not m:
        return text
    existing = {s.strip() for s in m.group(1).split(",") if s.strip()}
    missing = symbols - existing
    if not missing:
        return text
    new_block = (
        "import {\n  "
        + ",\n  ".join(sorted(existing | missing))
        + f',\n}} from "{import_path_for(file)}";'
    )
    return text[: m.start()] + new_block + text[m.end() :]


def transform_body(body: str) -> tuple[str, set[str]]:
    symbols: set[str] = set()
    new = body
    n1 = len(ROW_FLEX.findall(new))
    if n1:
        new = ROW_FLEX.sub("${vuiOpaqueRowClass}", new)
        symbols.add("vuiOpaqueRowClass")
    n2 = len(PANEL_FLEX.findall(new))
    if n2:
        new = PANEL_FLEX.sub("${vuiFlatPanelClass}", new)
        symbols.add("vuiFlatPanelClass")
    n3 = len(GLASS_FLEX.findall(new))
    if n3:
        new = GLASS_FLEX.sub("${vuiGlassPanelClass}", new)
        symbols.add("vuiGlassPanelClass")
    n4 = len(ROW_ARB_FLEX.findall(new))
    if n4:
        new = ROW_ARB_FLEX.sub("${vuiOpaqueRowClass}", new)
        symbols.add("vuiOpaqueRowClass")
    n5 = len(PANEL_ARB_FLEX.findall(new))
    if n5:
        new = PANEL_ARB_FLEX.sub("${vuiFlatPanelClass}", new)
        symbols.add("vuiFlatPanelClass")
    return new, symbols


def process_file(path: Path) -> bool:
    original = path.read_text(encoding="utf-8")
    text = original
    all_syms: set[str] = set()

    def sub_dq(m: re.Match[str]) -> str:
        key, body = m.group(1), m.group(2)
        new_body, syms = transform_body(body)
        all_syms.update(syms)
        if new_body == body:
            return m.group(0)
        if "${" in new_body:
            return f"{key}: `{new_body.replace('`', '\\`')}`,"
        return f'{key}: "{new_body}",'

    def sub_bt(m: re.Match[str]) -> str:
        key, body = m.group(1), m.group(2)
        new_body, syms = transform_body(body)
        all_syms.update(syms)
        if new_body == body:
            return m.group(0)
        return f"{key}: `{new_body}`,"

    text = re.sub(r"([A-Za-z0-9_]+):\s*\"((?:\\.|[^\"\\])*)\",", sub_dq, text)
    text = re.sub(r"([A-Za-z0-9_]+):\s*`((?:\\.|[^`\\])*)`,", sub_bt, text)

    # Also transform bare multi-line template chunks less common

    if all_syms:
        text = ensure_import(text, path, all_syms)

    if text != original:
        path.write_text(text, encoding="utf-8", newline="\n")
        return True
    return False


def main() -> None:
    n = 0
    for path in sorted(ROOT.rglob("*.styles.ts")):
        if "test" in path.name.lower():
            continue
        if process_file(path):
            n += 1
            print("OK", path.relative_to(ROOT.parent))
    print("changed", n)


if __name__ == "__main__":
    main()
