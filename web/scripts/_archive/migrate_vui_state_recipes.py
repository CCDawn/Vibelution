#!/usr/bin/env python3
"""Wave 2B: fold high-frequency state-tint class strings into vuiSurfaceRecipes.

Does not collapse whitespace or reformat style maps beyond fragment replacement
and import merging.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
RECIPES = "design/vuiSurfaceRecipes"

# Longest / most-specific first.
REPLACEMENTS: list[tuple[str, str]] = [
    (
        "border-[color-mix(in_srgb,var(--accent-cool)_38%,transparent)] "
        "bg-[color-mix(in_srgb,var(--accent-cool)_11%,transparent)] "
        "text-[var(--accent-cool)] "
        "border-[color-mix(in_srgb,var(--accent-cool)_34%,transparent)] "
        "bg-[color-mix(in_srgb,var(--accent-cool)_10%,var(--vui-surface-row))]",
        "vuiStateSelectedRowClass",
    ),
    (
        "border-[color-mix(in_srgb,var(--accent-cool)_34%,transparent)] "
        "bg-[color-mix(in_srgb,var(--accent-cool)_10%,var(--vui-surface-row))] "
        "text-[var(--accent-cool)]",
        "vuiStateSelectedRowClass",
    ),
    (
        "border-[color-mix(in_srgb,var(--accent-cool)_34%,transparent)] "
        "bg-[color-mix(in_srgb,var(--accent-cool)_10%,var(--vui-surface-row))]",
        "vuiStateSelectedRowClass",
    ),
    (
        "border-[color-mix(in_srgb,var(--accent-cool)_38%,transparent)] "
        "bg-[color-mix(in_srgb,var(--accent-cool)_11%,transparent)] "
        "text-[var(--accent-cool)]",
        "vuiStateCoolSoftClass",
    ),
    (
        "border-[color-mix(in_srgb,var(--accent-cool)_28%,transparent)] "
        "bg-[color-mix(in_srgb,var(--accent-cool)_8%,transparent)] "
        "text-[var(--accent-cool)]",
        "vuiStateCoolInfoClass",
    ),
    (
        "border-[color-mix(in_srgb,var(--state-error)_36%,transparent)] "
        "bg-[color-mix(in_srgb,var(--state-error)_9%,transparent)] "
        "text-[var(--state-error)]",
        "vuiStateDangerSoftClass",
    ),
    (
        "border-[color-mix(in_srgb,var(--state-error)_34%,transparent)] "
        "bg-[color-mix(in_srgb,var(--state-error)_10%,transparent)] "
        "text-[var(--state-error)]",
        "vuiStateDangerSoftClass",
    ),
    (
        "border-[color-mix(in_srgb,var(--state-success)_28%,transparent)] "
        "bg-[color-mix(in_srgb,var(--state-success)_9%,transparent)] "
        "text-[var(--state-success)]",
        "vuiStateSuccessSoftClass",
    ),
    (
        "border-[color-mix(in_srgb,var(--accent-warm)_30%,transparent)] "
        "bg-[color-mix(in_srgb,var(--accent-warm)_10%,transparent)] "
        "text-[var(--accent-warm-2)]",
        "vuiStateWarmSoftClass",
    ),
    (
        "rounded-[var(--radius-panel)] border "
        "border-[color-mix(in_srgb,var(--state-error)_22%,var(--vui-border-subtle))] "
        "bg-[color-mix(in_srgb,var(--state-error)_4%,var(--vui-surface-panel))]",
        "vuiStateDangerPanelClass",
    ),
    (
        "rounded-[var(--radius-panel)] border "
        "border-[color-mix(in_srgb,var(--state-warning)_42%,var(--vui-border-subtle))] "
        "bg-[color-mix(in_srgb,var(--state-warning)_8%,var(--vui-surface-panel))]",
        "vuiStateWarningPanelClass",
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
        i = m2.end()
        return source[:i] + import_line + "\n" + source[i:]
    return import_line + "\n" + source


def quote_context_at(source: str, index: int) -> str:
    """Return 'template' | 'double' | 'single' | 'none' for string context at index."""
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
                # skip ${...} expression roughly by brace depth
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
    """Return (open_quote_index, close_quote_index) for the string containing index."""
    if kind == "template":
        q = "`"
    elif kind == "double":
        q = '"'
    elif kind == "single":
        q = "'"
    else:
        return None
    # walk backward to open quote
    i = index - 1
    open_i = None
    while i >= 0:
        if source[i] == q:
            # count backslashes for escaped?
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
    # walk forward from after open to close
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
    # Process replacements from left to right, re-scanning after each full pass order
    for frag, symbol in REPLACEMENTS:
        while True:
            idx = source.find(frag)
            if idx < 0:
                break
            kind = quote_context_at(source, idx)
            bounds = find_string_bounds(source, idx, kind)
            if bounds is None:
                # unexpected: skip one char to avoid infinite loop
                source = source[:idx] + source[idx + 1 :]
                continue
            open_i, close_i = bounds
            # replace fragment with ${symbol} inside the string body
            body_start = open_i + 1
            body_end = close_i
            body = source[body_start:body_end]
            rel = idx - body_start
            new_body = body[:rel] + f"${{{symbol}}}" + body[rel + len(frag) :]
            if kind == "template":
                source = source[:body_start] + new_body + source[body_end:]
            elif kind == "double":
                # promote entire string to template literal
                source = source[:open_i] + "`" + new_body + "`" + source[close_i + 1 :]
            elif kind == "single":
                source = source[:open_i] + "`" + new_body.replace("`", "\\`") + "`" + source[close_i + 1 :]
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
    for path in sorted(ROOT.rglob("*.styles.ts")):
        if apply_file(path):
            changed.append(path.relative_to(ROOT).as_posix())
    for path in sorted(ROOT.rglob("*.styles.tsx")):
        if apply_file(path):
            changed.append(path.relative_to(ROOT).as_posix())
    print(f"updated {len(changed)} files")
    for p in changed:
        print(" ", p)


if __name__ == "__main__":
    main()
