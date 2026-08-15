"""Pass 5: wire remaining shell/const style maps onto VUI surface recipes."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"

# (substring, replacement symbol)
SUBS: list[tuple[str, str]] = [
    (
        "rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] !bg-[var(--vui-surface-panel)]",
        "vuiFlatPanelClass",
    ),
    (
        "rounded-[var(--radius-panel)] border border-vui-border-subtle !bg-[var(--vui-surface-panel)]",
        "vuiFlatPanelClass",
    ),
    (
        "rounded-[var(--radius-panel)] border border-vui-border-subtle bg-vui-surface-panel",
        "vuiFlatPanelClass",
    ),
    (
        "rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] !bg-[var(--vui-surface-row)]",
        "vuiOpaqueRowClass",
    ),
    (
        "rounded-[var(--radius-control)] border border-vui-border-subtle !bg-[var(--vui-surface-row)]",
        "vuiOpaqueRowClass",
    ),
    (
        "[border:1px_solid_var(--vui-border-subtle)] [border-radius:8px] [background:var(--vui-surface-row)]",
        "vuiOpaqueRowClass",
    ),
    (
        "rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-glass)]",
        "vuiGlassPanelClass",
    ),
    (
        "rounded-[var(--radius-panel)] border border-vui-border-subtle bg-vui-surface-glass",
        "vuiGlassPanelClass",
    ),
    ("bg-[var(--vui-surface-workspace)]", "vuiWorkspaceFillClass"),
    ("!bg-[var(--vui-surface-workspace)]", "vuiWorkspaceFillClass"),
    ("bg-vui-surface-workspace", "vuiWorkspaceFillClass"),
    ("bg-[var(--vui-surface-toolbar)]", "vuiToolbarFillClass"),
    ("!bg-[var(--vui-surface-toolbar)]", "vuiToolbarFillClass"),
    ("bg-vui-surface-toolbar", "vuiToolbarFillClass"),
    ("bg-[var(--vui-surface-rail)]", "vuiRailFillClass"),
    ("!bg-[var(--vui-surface-rail)]", "vuiRailFillClass"),
    ("bg-vui-surface-rail", "vuiRailFillClass"),
    ("bg-[var(--vui-surface-inset)]", "vuiInsetFillClass"),
    ("!bg-[var(--vui-surface-inset)]", "vuiInsetFillClass"),
]


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
            if s.startswith("//") or s.startswith("/*") or s.startswith("*") or s.strip() == "":
                i += 1
                continue
            break
        return "".join(lines[:i]) + imp + "".join(lines[i:])
    m = re.search(
        r"import\s*\{([^}]+)\}\s*from\s*([\"'][^\"']*vuiSurfaceRecipes[\"'])\s*;",
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
        + f',\n}} from {m.group(2)};'
    )
    return text[: m.start()] + new_block + text[m.end() :]


def transform_body(body: str) -> tuple[str, set[str]]:
    symbols: set[str] = set()
    new = body
    for needle, sym in SUBS:
        if needle in new and f"${{{sym}}}" not in new:
            # Don't replace state-tint only lines that merely mention surface-row inside color-mix
            if needle.startswith("bg-[var(--vui-surface-") or needle.startswith("!bg-[var(--vui-surface-"):
                # skip if this bg is only inside a longer color-mix we shouldn't touch — needle is exact
                pass
            new = new.replace(needle, f"${{{sym}}}", 1)
            symbols.add(sym)
    return new, symbols


def process_file(path: Path) -> bool:
    original = path.read_text(encoding="utf-8")
    if "vui-surface" not in original and "vui-surface" not in original.replace("surface-", ""):
        if "bg-vui-surface" not in original and "bg-[var(--vui-surface" not in original:
            # still check Tailwind token form
            if "vui-surface-" not in original and "bg-vui-surface" not in original:
                return False
    # Always try remaining files; even if already imported, fill may still need shell recipes
    text = original
    all_syms: set[str] = set()

    def sub_quoted(m: re.Match[str]) -> str:
        prefix, quote, body, end = m.group(1), m.group(2), m.group(3), m.group(4)
        new_body, syms = transform_body(body)
        all_syms.update(syms)
        if new_body == body:
            return m.group(0)
        if "${" in new_body:
            return f"{prefix}`{new_body.replace('`', '\\`')}`"
        return f"{prefix}{quote}{new_body}{end}"

    # const x = "..."
    text = re.sub(
        r"(const\s+[A-Za-z0-9_]+\s*=\s*)([\"'])((?:\\.|(?!\2).)*)(\2)",
        sub_quoted,
        text,
    )
    # key: "..."
    def sub_prop(m: re.Match[str]) -> str:
        key, body = m.group(1), m.group(2)
        new_body, syms = transform_body(body)
        all_syms.update(syms)
        if new_body == body:
            return m.group(0)
        if "${" in new_body:
            return f"{key}: `{new_body.replace('`', '\\`')}`,"
        return f'{key}: "{new_body}",'

    text = re.sub(r"([A-Za-z0-9_]+):\s*\"((?:\\.|[^\"\\])*)\",", sub_prop, text)

    # key: `...`
    def sub_bt(m: re.Match[str]) -> str:
        key, body = m.group(1), m.group(2)
        new_body, syms = transform_body(body)
        all_syms.update(syms)
        if new_body == body:
            return m.group(0)
        return f"{key}: `{new_body}`,"

    text = re.sub(r"([A-Za-z0-9_]+):\s*`((?:\\.|[^`\\])*)`,", sub_bt, text)

    # const x = `...`
    def sub_const_bt(m: re.Match[str]) -> str:
        prefix, body = m.group(1), m.group(2)
        new_body, syms = transform_body(body)
        all_syms.update(syms)
        if new_body == body:
            return m.group(0)
        return f"{prefix}`{new_body}`"

    text = re.sub(r"(const\s+[A-Za-z0-9_]+\s*=\s*)`((?:\\.|[^`\\])*)`", sub_const_bt, text)

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
        # Prefer remaining non-recipe files first, but re-touch any file still using raw fills
        if process_file(path):
            n += 1
            print("OK", path.relative_to(ROOT.parent))
    print("changed", n)


if __name__ == "__main__":
    main()
