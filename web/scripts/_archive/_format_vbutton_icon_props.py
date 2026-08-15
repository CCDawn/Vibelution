"""Pretty-format compact VButton open tags that put icon= and children on one line.

Only rewrites lines that match:
  ... icon={...}>{children...}</VButton>
  ... icon={...} />
and are already single-line / densified by the icon-slot codemod.
Does not change semantics.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"


def find_matching_brace(s: str, open_idx: int) -> int:
    """open_idx points at '{'."""
    depth = 0
    i = open_idx
    in_s = in_d = False
    while i < len(s):
        ch = s[i]
        if in_s:
            if ch == "\\" and i + 1 < len(s):
                i += 2
                continue
            if ch == "'":
                in_s = False
            i += 1
            continue
        if in_d:
            if ch == "\\" and i + 1 < len(s):
                i += 2
                continue
            if ch == '"':
                in_d = False
            i += 1
            continue
        if ch == "'":
            in_s = True
            i += 1
            continue
        if ch == '"':
            in_d = True
            i += 1
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def reformat_line(line: str) -> str | None:
    """Return rewritten line(s) or None if no change."""
    stripped = line.lstrip()
    if "<VButton" not in stripped and "icon={" not in stripped:
        return None
    # Must have icon= and either children close or self-close on same line
    if "icon={" not in line:
        return None
    if "</VButton>" not in line and not re.search(r"icon=\{.*\} />\s*$", line):
        return None
    # Skip already multi-line (caller only gives one line)
    indent = line[: len(line) - len(line.lstrip())]
    # Find last icon={ or trailingIcon={ on this line that sits just before >
    # Prefer the prop immediately before children >
    m = None
    for prop in ("trailingIcon={", "icon={"):
        idx = line.rfind(prop)
        if idx < 0:
            continue
        brace_open = idx + len(prop) - 1  # points at {
        brace_close = find_matching_brace(line, brace_open)
        if brace_close < 0:
            continue
        after = line[brace_close + 1 :]
        # self-closing
        if re.match(r"\s*/>\s*$", after):
            # Pretty: put icon prop on own structure if whole tag is one long line
            if len(line) < 120:
                return None
            # extract attrs before prop
            open_m = re.search(r"<VButton\b", line)
            if not open_m:
                return None
            # keep as-is if already short enough
            return None
        # children form: }>{...}</VButton>
        child_m = re.match(r"\s*>([\s\S]*)</VButton>\s*$", after)
        if not child_m:
            continue
        children = child_m.group(1)
        # Only reformat if children are non-empty and tag is dense
        if not children.strip():
            return None
        if len(line) < 100 and "\n" not in children:
            # still reformat if icon and children glued: }>< or }>{
            if not re.search(r"\}\s*>\s*(?:\{|<span|[^\s])", line[idx:]):
                return None
        prop_name = "trailingIcon" if prop.startswith("trailing") else "icon"
        # head is everything before prop= (trim trailing space)
        head = line[:idx].rstrip()
        icon_expr = line[brace_open : brace_close + 1]  # includes braces
        # head should end with VButton attrs; ensure space before prop when single-line attrs
        # Build multi-line if head has many attrs or line is long
        child_indent = indent + "  "
        close_indent = indent
        # If head is `<VButton ...` without newline, put props on next lines when long
        if "\n" not in head and len(line) > 90:
            # split: open tag attrs on first line, icon prop, then children, close
            # head might be: `            <VButton type="button" className={...}`
            # or include other props already
            new = (
                f"{head}\n"
                f"{child_indent}{prop_name}={icon_expr}\n"
                f"{indent}>\n"
                f"{child_indent}{children.strip()}\n"
                f"{close_indent}</VButton>"
            )
            return new
        # shorter: just break children
        new = (
            f"{head} {prop_name}={icon_expr}>\n"
            f"{child_indent}{children.strip()}\n"
            f"{close_indent}</VButton>"
        )
        return new
    return None


def process_text(text: str) -> tuple[str, int]:
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    n = 0
    for line in lines:
        nl = "\n" if line.endswith("\n") else ""
        core = line[:-1] if nl else line
        if core.endswith("\r"):
            core = core[:-1]
        rewritten = reformat_line(core)
        if rewritten is None:
            out.append(line)
        else:
            out.append(rewritten + (nl or "\n"))
            n += 1
    return "".join(out), n


def main() -> None:
    total = 0
    files = 0
    for path in sorted(ROOT.rglob("*.tsx")):
        original = path.read_text(encoding="utf-8")
        updated, n = process_text(original)
        if n and updated != original:
            path.write_text(updated, encoding="utf-8", newline="\n")
            files += 1
            total += n
            print(f"{n:3d} {path.relative_to(ROOT)}")
    print(f"FORMATTED {total} in {files} files")


if __name__ == "__main__":
    main()
