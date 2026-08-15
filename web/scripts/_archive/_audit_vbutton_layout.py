"""Audit VButton for icon-as-child / multi-child label-slot breakage.

Ignores:
- contentLayout=\"plain\"
- isIconOnly

Parses open tags with brace/string awareness so JSX attrs like
icon={<Foo size={15} />} do not terminate the open tag early.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"

# Any self-closing PascalCase tag with size={N} is treated as an icon candidate.
ICON_SELF_CLOSE = re.compile(
    r"<([A-Z][A-Za-z0-9]*)\b[^>]*\bsize=\{\d+\}[^>]*/>"
)
# Also bare icon-like self-closing without size (rarer)
BARE_ICONISH = re.compile(
    r"<(Arrow(?:Right|Left|Up|Down|UpRight|DownRight)|"
    r"Chevron(?:Right|Left|Up|Down)|"
    r"Plus|X|Check|Save|Trash2?|Search|RefreshCw|RotateCcw|"
    r"Pencil|Edit2?|Settings2?|ExternalLink|Download|Upload|"
    r"Play|Square|Copy|Send|Bot|Loader(?:Circle|2)?|"
    r"PanelTop(?:Open|Close)|Wrench|Power|BrainCircuit|"
    r"Sun|Moon|Archive|Users(?:Round)?|Compass|"
    r"MessageSquare|Link2|MoreHorizontal|Ellipsis|"
    r"CheckSquare|CheckCircle2|CircleSlash|"
    r"ArrowUpRight|Sparkles)\b[^>]*/>"
)


def find_open_tag_end(text: str, open_idx: int) -> int:
    """Return index of '>' that closes the open tag, respecting strings and braces."""
    j = open_idx + len("<VButton")
    brace = 0
    in_s = in_d = False
    while j < len(text):
        ch = text[j]
        if in_s:
            if ch == "\\" and j + 1 < len(text):
                j += 2
                continue
            if ch == "'":
                in_s = False
            j += 1
            continue
        if in_d:
            if ch == "\\" and j + 1 < len(text):
                j += 2
                continue
            if ch == '"':
                in_d = False
            j += 1
            continue
        if ch == "'":
            in_s = True
            j += 1
            continue
        if ch == '"':
            in_d = True
            j += 1
            continue
        if ch == "{":
            brace += 1
            j += 1
            continue
        if ch == "}":
            brace = max(0, brace - 1)
            j += 1
            continue
        if ch == ">" and brace == 0:
            return j
        j += 1
    return -1


def iter_vbuttons(text: str):
    start = 0
    while True:
        idx = text.find("<VButton", start)
        if idx < 0:
            return
        after = idx + len("<VButton")
        if after < len(text) and (text[after].isalnum() or text[after] == "_"):
            start = after
            continue
        gt = find_open_tag_end(text, idx)
        if gt < 0:
            return
        open_tag = text[idx : gt + 1]
        if open_tag.rstrip().endswith("/>"):
            start = gt + 1
            continue
        body_start = gt + 1
        depth = 1
        pos = body_start
        while depth > 0 and pos < len(text):
            next_open = text.find("<VButton", pos)
            next_close = text.find("</VButton>", pos)
            if next_close < 0:
                return
            while next_open >= 0:
                ao = next_open + len("<VButton")
                if ao < len(text) and (text[ao].isalnum() or text[ao] == "_"):
                    next_open = text.find("<VButton", ao)
                    continue
                break
            if next_open >= 0 and next_open < next_close:
                depth += 1
                pos = next_open + 8
            else:
                depth -= 1
                if depth == 0:
                    body = text[body_start:next_close]
                    yield idx, open_tag, body
                    start = next_close + len("</VButton>")
                    break
                pos = next_close + len("</VButton>")


def has_prop(open_tag: str, name: str) -> bool:
    return re.search(rf"\b{name}\s*=", open_tag) is not None


def body_icons(body: str) -> list[str]:
    names = ICON_SELF_CLOSE.findall(body)
    if not names:
        names = BARE_ICONISH.findall(body)
    return names


def main() -> None:
    issues: list[tuple[str, str, str, str]] = []
    for path in sorted(ROOT.rglob("*.tsx")):
        text = path.read_text(encoding="utf-8", errors="replace")
        rel = str(path.relative_to(ROOT)).replace("\\", "/")
        for idx, open_tag, body in iter_vbuttons(text):
            if 'contentLayout="plain"' in open_tag or "contentLayout='plain'" in open_tag:
                continue
            if "isIconOnly" in open_tag:
                continue
            has_icon_prop = has_prop(open_tag, "icon") or has_prop(open_tag, "trailingIcon")
            icons = body_icons(body)
            tags = re.findall(r"<([A-Z][A-Za-z0-9]*)\b", body)
            significant = [n for n in tags if n not in {"span", "strong", "em", "code", "div"}]
            kind = ""
            if icons and not has_icon_prop:
                kind = "icon-as-child"
            elif icons and has_icon_prop:
                kind = "icon-prop+body-icon"
            elif len(significant) >= 2 and not has_icon_prop:
                kind = "multi-child"
            if not kind:
                continue
            line = text.count("\n", 0, idx) + 1
            snippet = re.sub(r"\s+", " ", body).strip()[:140]
            issues.append((kind, f"{rel}:{line}", ",".join(sorted(set(icons))) or f"tags={significant}", snippet))

    print(f"TOTAL {len(issues)}")
    by_file: dict[str, int] = {}
    by_kind: dict[str, int] = {}
    for kind, loc, icons, snippet in issues:
        file = loc.split(":")[0]
        by_file[file] = by_file.get(file, 0) + 1
        by_kind[kind] = by_kind.get(kind, 0) + 1
        print(f"{kind}\t{loc}\t{icons}")
        print(f"  {snippet}")
    print("\nBY_KIND")
    for kind, count in sorted(by_kind.items(), key=lambda item: (-item[1], item[0])):
        print(f"{count:3d} {kind}")
    print("\nBY_FILE")
    for file, count in sorted(by_file.items(), key=lambda item: (-item[1], item[0])):
        print(f"{count:3d} {file}")


if __name__ == "__main__":
    main()
