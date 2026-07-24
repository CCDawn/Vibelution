#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path

root = Path(__file__).resolve().parents[1] / "src"
rows: list[dict] = []

for f in sorted(root.rglob("*.styles.ts")):
    t = f.read_text(encoding="utf-8")
    rel = f.relative_to(root).as_posix()
    has_rec = "vuiSurfaceRecipes" in t
    if has_rec:
        continue
    has_surface = bool(re.search(r"--vui-surface|vui-surface-", t))
    has_mix = "color-mix" in t
    has_legacy = bool(re.search(r"var\(--surface-", t))
    surface_roles = sorted(set(re.findall(r"--vui-surface-([a-z0-9-]+)", t)))
    # heuristic role
    role = "layout-only"
    if has_legacy:
        role = "legacy-surface-debt"
    elif not has_surface and not has_mix:
        role = "no-surface-token"
    elif has_mix and has_surface:
        if re.search(r"transparent", t) and re.search(
            r"color-mix\([^)]*--vui-surface-[^)]*transparent", t, re.I
        ):
            # surface first + transparent?
            role = "review-soft-or-structure"
        else:
            role = "state-tint-or-blend"
    elif has_surface:
        role = "surface-token-no-recipe"
    elif has_mix:
        role = "mix-no-surface"

    note_bits = []
    if surface_roles:
        note_bits.append("tokens=" + ",".join(surface_roles[:8]))
    if re.search(r"ring-offset", t):
        note_bits.append("ring-offset")
    if re.search(r"hover:", t) and has_surface:
        note_bits.append("hover")
    if re.search(r"glass|overlay|popover", t, re.I):
        note_bits.append("overlay-ish")

    rows.append(
        {
            "file": rel,
            "role": role,
            "has_surface": has_surface,
            "has_mix": has_mix,
            "notes": "; ".join(note_bits) or "-",
            "bytes": len(t),
        }
    )

print(f"count={len(rows)}")
for r in rows:
    print(f"{r['file']}\t{r['role']}\t{r['has_surface']}\t{r['has_mix']}\t{r['notes']}\t{r['bytes']}")
