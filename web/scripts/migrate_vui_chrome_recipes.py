#!/usr/bin/env python3
"""Wave 3A: fold quiet control chrome strings into vuiChromeRecipes."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
RECIPES = "design/vuiChromeRecipes"

# Longest first.
REPLACEMENTS: list[tuple[str, str]] = [
    (
        "inline-flex min-h-[var(--vui-control-height-sm)] w-fit max-w-full items-center justify-center gap-1.5 "
        "rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] "
        "px-2 py-1 [font-size:var(--vui-font-xs)] font-semibold leading-tight text-[var(--fg-secondary)] "
        "hover:border-[var(--vui-control-hover-border)] hover:bg-[var(--vui-control-hover-bg)] "
        "hover:text-[var(--vui-control-hover-fg)] disabled:cursor-default disabled:opacity-55",
        "vuiControlQuietClass",
    ),
    (
        "min-h-[var(--vui-control-height-sm)] w-fit max-w-full items-center justify-center gap-1.5 "
        "rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] "
        "px-2 py-1 [font-size:var(--vui-font-xs)] font-semibold leading-tight text-[var(--fg-secondary)] "
        "hover:border-[var(--vui-control-hover-border)] hover:bg-[var(--vui-control-hover-bg)] "
        "hover:text-[var(--vui-control-hover-fg)] disabled:cursor-default disabled:opacity-55",
        "vuiControlQuietChromeClass",
    ),
    (
        "inline-flex min-h-6 w-fit max-w-full items-center justify-center gap-1.5 rounded-full "
        "border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 "
        "[font-size:var(--vui-font-xs)] font-semibold leading-none text-[var(--fg-secondary)]",
        "vuiControlPillClass",
    ),
]

IMPORT_RE = re.compile(
    r'import\s*\{([^}]*)\}\s*from\s*["\']([^"\']*vuiChromeRecipes)["\']\s*;',
    re.M,
)
ANY_IMPORT_RE = re.compile(
    r'import\s*\{([^}]*)\}\s*from\s*["\']([^"\']*vui(?:Chrome|Surface)Recipes)["\']\s*;',
    re.M,
)


def rel_import(file: Path) -> str:
    depth = len(file.relative_to(ROOT).parts) - 1
    return ("../" * depth if depth else "./") + RECIPES


def ensure_import(source: str, file: Path, symbols: set[str]) -> str:
    if not symbols:
        return source
    m = IMPORT_RE.search(source)
    if m:
        existing = {s.strip() for s in m.group(1).split(",") if s.strip()}
        merged = sorted(existing | symbols)
        block = "import {\n  " + ",\n  ".join(merged) + f',\n}} from "{m.group(2)}";'
        return source[: m.start()] + block + source[m.end() :]
    # Prefer separate import after last import
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


def quote_context_at(source: str, index: int) -> str:
    in_template = in_double = in_single = False
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
    q = {"template": "`", "double": '"', "single": "'"}.get(kind)
    if not q:
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
            body = source[open_i + 1 : close_i]
            rel = idx - (open_i + 1)
            new_body = body[:rel] + f"${{{symbol}}}" + body[rel + len(frag) :]
            if kind == "template":
                source = source[: open_i + 1] + new_body + source[close_i:]
            else:
                source = source[:open_i] + "`" + new_body + "`" + source[close_i + 1 :]
            used.add(symbol)
    return source, used


def apply_file(path: Path) -> bool:
    if path.name in {"vuiChromeRecipes.ts", "vuiSurfaceRecipes.ts"}:
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
    changed = []
    for path in sorted(ROOT.rglob("*.styles.ts")):
        if apply_file(path):
            changed.append(path.relative_to(ROOT).as_posix())
    print(f"updated {len(changed)} files")
    for p in changed:
        print(" ", p)


if __name__ == "__main__":
    main()
