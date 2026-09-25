#!/usr/bin/env python3
"""normalise_book_column.py  --  canonicalise the hand-entered Book column

The `Book` column of `alignment_adjusted.xlsx` was typed by hand from the RSPB
Handbook, so the habitat names drift from the project's canonical labels:

    'Saltwater, Coastal, Built-Up'                     -> case drift
    'Woodland, Seminatural grassland; mountain, heath, bog.'
                                                       -> missing hyphen, trailing '.'
    'Mointain, heath, bog; improved grassland, coastal' -> typo
    'Mountian, heath, bog'                              -> typo

This rewrites each Book cell to the exact canonical labels from `_agent_common`,
separated by SEMICOLONS:

    Arable; Mountain, heath and bog; Improved grassland

Semicolons matter because one canonical label -- "Mountain, heath and bog" --
itself contains commas, so comma separation is genuinely ambiguous.

ORDER is preserved as the author typed it (first mention wins); this is a
formatting pass, not a reordering. Duplicates are collapsed.

TYPOS ARE CORRECTED, NOT DROPPED. A strict label match would silently lose
"Mointain"/"Mountian" (Curlew, Redpoll) -- turning a typo into missing data, the
worst outcome for a validation anchor. A small fuzzy pass catches them and every
correction is printed for review.

Anything that cannot be resolved to a canonical class is reported and the cell is
LEFT UNCHANGED rather than guessed at.

Only the Book column is touched. Data, Agent, Data-LLM, Data-Book and the
free-text note columns are untouched, as is the original alignment.xlsx.

Usage:
    python code/habitat_agents/normalise_book_column.py
    python code/habitat_agents/normalise_book_column.py --dry-run
"""

from __future__ import annotations

import argparse
import difflib
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _agent_common as ac  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
CODE_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
_m = re.search(r"(.*)/\.claude/worktrees/[^/]+$", CODE_ROOT)
DATA_ROOT = _m.group(1) if _m else CODE_ROOT

TARGET_XLSX = os.path.join(DATA_ROOT, "alignment_adjusted.xlsx")
SHEET = "alignment"
BOOK_COL_NAME = "Book"

CATEGORIES = ac.CATEGORIES
LABELS = ac.CATEGORY_LABELS
SEP = "; "

# Extra spellings seen in the hand-typed cells that a plain label match misses.
# Keys are normalised (letters only, lowercased).
ALIASES = {
    "seminaturalgrassland": "seminat_grassland",
    "seminatgrassland": "seminat_grassland",
    "builtup": "builtup",
    "mountainheathandbog": "mountain_heath_bog",
    "mountainheathbog": "mountain_heath_bog",
    "mountainheath": "mountain_heath_bog",
    "mointainheathbog": "mountain_heath_bog",      # typo: Curlew
    "mountianheathbog": "mountain_heath_bog",      # typo: Redpoll
    "heath": "mountain_heath_bog",
    "bog": "mountain_heath_bog",
}


def norm(s: str) -> str:
    """Letters only, lowercased -- kills case, punctuation and spacing drift."""
    return re.sub(r"[^a-z]", "", str(s).lower())


# Canonical lookup: normalised label -> slug, plus the slug itself.
CANON = {}
for _slug in CATEGORIES:
    CANON[norm(LABELS[_slug])] = _slug
    CANON[norm(_slug)] = _slug
CANON.update(ALIASES)


def split_fragments(text: str) -> list[str]:
    """Split a Book cell into candidate habitat fragments.

    Splitting on both ';' and ',' would tear "Mountain, heath and bog" apart, so
    protect that phrase first, split, then restore.
    """
    s = str(text).strip().rstrip(".").strip()
    # Protect the multi-word comma-containing class in all its typo variants.
    protected = re.sub(
        r"m[a-z]*(?:ountain|ountian|ointain)[a-z]*\s*,?\s*heath\s*,?\s*(?:and\s+)?bog",
        "@MHB@", s, flags=re.I,
    )
    parts = re.split(r"[;,]", protected)
    return [p.strip() for p in parts if p.strip()]


def resolve(fragment: str) -> tuple[str | None, bool]:
    """Map one fragment to a slug. Returns (slug|None, was_fuzzy)."""
    if fragment == "@MHB@":
        return "mountain_heath_bog", False
    key = norm(fragment)
    if not key:
        return None, False
    if key in CANON:
        return CANON[key], False
    # Substring: handles "improved grassland (arable margins)" style additions.
    for cand, slug in CANON.items():
        if cand and (cand in key or key in cand) and len(key) > 3:
            return slug, False
    # Fuzzy last resort -- catches unseen typos rather than dropping the habitat.
    match = difflib.get_close_matches(key, list(CANON.keys()), n=1, cutoff=0.82)
    if match:
        return CANON[match[0]], True
    return None, False


def canonicalise(text: str) -> tuple[str | None, list[str], list[str]]:
    """Return (canonical_string, fuzzy_notes, unresolved_fragments).

    canonical_string is None when nothing resolved (caller leaves the cell alone).
    Author's order preserved, duplicates collapsed.
    """
    slugs: list[str] = []
    fuzzy: list[str] = []
    unresolved: list[str] = []
    for frag in split_fragments(text):
        slug, was_fuzzy = resolve(frag)
        if slug is None:
            unresolved.append(frag)
            continue
        if was_fuzzy:
            fuzzy.append(f"{frag!r} -> {LABELS[slug]}")
        if slug not in slugs:
            slugs.append(slug)
    if not slugs:
        return None, fuzzy, unresolved
    return SEP.join(LABELS[s] for s in slugs), fuzzy, unresolved


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="Report changes without writing the file.")
    ap.add_argument("--file", default=TARGET_XLSX, help="Workbook to normalise.")
    args = ap.parse_args()

    from openpyxl import load_workbook

    if not os.path.exists(args.file):
        sys.exit(f"ERROR: workbook not found:\n  {args.file}")

    print("=" * 78)
    print("normalise_book_column.py -- canonical labels, semicolon-separated")
    print("=" * 78)
    print(f"\nWorkbook: {args.file}")
    print("Canonical labels:")
    for s in CATEGORIES:
        print(f"  {LABELS[s]}")
    print()

    wb = load_workbook(args.file)
    ws = wb[SHEET]

    book_col = None
    for cell in ws[1]:
        if cell.value and str(cell.value).strip() == BOOK_COL_NAME:
            book_col = cell.column
            break
    if book_col is None:
        sys.exit(f"ERROR: no '{BOOK_COL_NAME}' column in sheet '{SHEET}'.")

    n_seen = n_changed = 0
    all_fuzzy: list[tuple[str, list[str]]] = []
    all_unresolved: list[tuple[str, list[str]]] = []
    changes: list[tuple[str, str, str]] = []

    for r in range(2, ws.max_row + 1):
        raw = ws.cell(row=r, column=book_col).value
        if raw is None or str(raw).strip() == "":
            continue
        n_seen += 1
        species = str(ws.cell(row=r, column=1).value or f"row {r}")

        canon, fuzzy, unresolved = canonicalise(raw)
        if fuzzy:
            all_fuzzy.append((species, fuzzy))
        if unresolved:
            all_unresolved.append((species, unresolved))
        if canon is None:
            continue
        if canon != str(raw):
            changes.append((species, str(raw), canon))
            n_changed += 1
            if not args.dry_run:
                ws.cell(row=r, column=book_col, value=canon)

    print(f"Book cells: {n_seen} filled, {n_changed} rewritten.\n")

    if changes:
        print("Rewrites:")
        for species, old, new in changes:
            print(f"  {species}")
            print(f"     was: {old}")
            print(f"     now: {new}")
        print()

    if all_fuzzy:
        print("Typos corrected (fuzzy match -- please eyeball these):")
        for species, notes in all_fuzzy:
            for n in notes:
                print(f"  {species}: {n}")
        print()

    if all_unresolved:
        print("UNRESOLVED fragments (cell left unchanged -- needs a human):")
        for species, frags in all_unresolved:
            print(f"  {species}: {', '.join(repr(f) for f in frags)}")
        print()
    else:
        print("All fragments resolved to a canonical class.\n")

    if args.dry_run:
        print("DRY RUN -- nothing written.")
        return

    wb.save(args.file)
    print(f"Wrote {args.file}")
    print("  Only the Book column was modified.")


if __name__ == "__main__":
    main()
