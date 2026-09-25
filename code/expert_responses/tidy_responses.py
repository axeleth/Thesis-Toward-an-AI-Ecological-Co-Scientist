#!/usr/bin/env python3
"""tidy_responses.py  --  reshape the expert-survey Google Form export
=====================================================================

The Google Form export is one row per respondent and one column per species,
with each habitat answer a comma-joined string ("Saltwater, Coastal"). The
question headers contain embedded newlines, so the file *looks* mangled in a
line-oriented viewer -- it is not. Any RFC-4180 parser reads it correctly.

This script turns that into the shape the analysis wants:

    species as rows, one column per respondent

and writes three files:

  * ``expert_responses_wide.csv``  -- 41 rows x (2 + N respondents).
    Each cell is that respondent's comma-joined habitat picks for that species.
    This is the "nicer format" for reading by eye.

  * ``expert_responses_long.csv``  -- OFF BY DEFAULT; pass ``--long``.
    One row per (species, respondent, habitat) tick, with the frozen
    9-class slug attached. Each species therefore spans several rows --
    one per habitat ticked -- rather than one row listing them all. That
    makes it the form to join downstream: ``category_slug`` merges
    straight onto the eBird presence matrices without re-parsing the
    comma-joined habitat strings in the wide file.

  * ``expert_responses_matrix.csv`` -- species x 9 habitat columns holding
    the COUNT of respondents who ticked each habitat, plus ``n_respondents``
    and ``n_dont_know``. With one respondent this is effectively boolean; it
    becomes a consensus tally as more responses arrive.

Design notes for reuse (more responses are expected)
----------------------------------------------------
* **Respondent count is inferred**, never assumed. Adding rows to the export
  just widens the wide/matrix output.
* **Species rows are pinned to the canonical 41** in ``focal_species.json``
  and emitted in canonical order, so the output stays row-aligned with the
  eBird matrices regardless of the order the form used. A species that the
  form omits still gets a row (blank), and a form species that is not in the
  canonical set is a hard error rather than a silent drop.
* **Habitat labels are mapped to the frozen 9 slugs** from
  ``llm_study/categories.json``. An unrecognised label is a hard error -- if
  the form's wording ever drifts from the frozen labels, that must surface
  loudly rather than produce a silently empty column.
* "I don't know" is preserved as its own signal (it is NOT the same as no
  ticks) and counted separately in ``n_dont_know``.
* Blank spacer rows in the export (all fields empty) are dropped.

Usage
-----
    python code/expert_responses/tidy_responses.py                 # wide + matrix
    python code/expert_responses/tidy_responses.py --long          # also long
    python code/expert_responses/tidy_responses.py --csv PATH ...  # explicit
    python code/expert_responses/tidy_responses.py --outdir DIR

This script sits in ``code/expert_responses/`` alongside the Form exports it
reads. The default input is the newest ``*.csv`` in that same directory, and
outputs go to its ``tidy/`` subdirectory; both are resolved from the script's
own location, so it works from any working directory. Note the directory is
gitignored (``*.csv``), so the responses themselves live only in the working
copy -- only this script is tracked.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from collections import Counter

# This script lives in the responses directory itself, so HERE *is* the
# default input directory and the code/ root is one level up.
HERE = os.path.dirname(os.path.abspath(__file__))
CODE_DIR = os.path.dirname(HERE)

sys.path.insert(0, CODE_DIR)
import focal_species as fs  # noqa: E402  (needs the path above)

DEFAULT_INPUT_DIR = HERE
DEFAULT_OUTDIR = os.path.join(HERE, "tidy")
CATEGORIES_JSON = os.path.join(CODE_DIR, "llm_study", "categories.json")

# Header cells look like "European Shag [1/41]\nTick all the habitats where..."
SPECIES_HEADER_RE = re.compile(r"^(?P<name>.*?)\s*\[(?P<idx>\d+)\s*/\s*\d+\]", re.S)

DONT_KNOW = "I don't know"

# The form's species wording vs. the canonical common_name. `red_list_name`
# in focal_species.json covers most divergences (e.g. Slavonian grebe); these
# are the leftovers the form spells differently again.
FORM_NAME_ALIASES = {
    "leach's petrel": "lcspet",  # canonical: "Leach's Storm-Petrel"
}

# Habitat label as it appears in the form -> frozen category slug. Built from
# categories.json, plus tolerated spelling variants seen in the live form.
EXTRA_LABEL_ALIASES = {
    # The deployed form misspells "heath" as "heat" (flagged by a respondent).
    # Tolerated here so existing responses parse; fix the form for future runs.
    "mountain, heat and bog": "mountain_heath_bog",
}


class TidyError(RuntimeError):
    """Raised when the export cannot be reconciled with the frozen schema."""


def _norm(s: str) -> str:
    """Whitespace/case-normalise a label for tolerant matching."""
    return re.sub(r"\s+", " ", (s or "").replace("’", "'")).strip().lower()


def load_categories(path: str = CATEGORIES_JSON) -> tuple[list[str], dict[str, str], dict[str, str]]:
    """Return (slugs in frozen order, slug->label, normalised label->slug)."""
    with open(path, "r", encoding="utf-8") as fh:
        doc = json.load(fh)
    cats = doc["categories"]
    slugs = [c["slug"] for c in cats]
    slug_to_label = {c["slug"]: c["label"] for c in cats}
    label_to_slug = {_norm(c["label"]): c["slug"] for c in cats}
    for alias, slug in EXTRA_LABEL_ALIASES.items():
        if slug not in slug_to_label:
            raise TidyError(f"alias {alias!r} points at unknown slug {slug!r}")
        label_to_slug[_norm(alias)] = slug
    return slugs, slug_to_label, label_to_slug


def build_species_lookup() -> tuple[list[dict], dict[str, str]]:
    """Return (canonical species records, normalised form-name -> ebird_code)."""
    species = fs.load_species()
    lookup: dict[str, str] = {}
    for s in species:
        code = s["ebird_code"]
        for key in (s.get("common_name"), s.get("red_list_name"), s.get("scientific_name")):
            if key:
                lookup[_norm(key)] = code
    for alias, code in FORM_NAME_ALIASES.items():
        lookup[_norm(alias)] = code
    return species, lookup


def find_default_csv(input_dir: str = DEFAULT_INPUT_DIR) -> str:
    """Newest .csv in the responses directory (excluding our own outputs)."""
    if not os.path.isdir(input_dir):
        raise TidyError(f"input directory not found: {input_dir}")
    candidates = [
        os.path.join(input_dir, f)
        for f in os.listdir(input_dir)
        if f.lower().endswith(".csv") and not f.startswith("expert_responses_")
    ]
    if not candidates:
        raise TidyError(
            f"no CSV found in {input_dir}. Export the Google Form responses there, "
            "or pass --csv explicitly."
        )
    return max(candidates, key=os.path.getmtime)


def parse_export(csv_path: str, species_lookup: dict[str, str]) -> tuple[list[dict], list[tuple[int, str]]]:
    """Read the export.

    Returns (respondents, species_columns) where each respondent is a dict of
    metadata plus ``answers`` {ebird_code: raw answer string}, and
    species_columns is [(column index, ebird_code)] in form order.
    """
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.reader(fh))

    if not rows:
        raise TidyError(f"{csv_path} is empty.")

    header = rows[0]
    species_columns: list[tuple[int, str]] = []
    meta_columns: dict[str, int] = {}
    unknown: list[str] = []

    for i, cell in enumerate(header):
        m = SPECIES_HEADER_RE.match(cell.strip())
        if m:
            name = m.group("name").strip()
            code = species_lookup.get(_norm(name))
            if code is None:
                unknown.append(name)
            else:
                species_columns.append((i, code))
            continue
        low = _norm(cell)
        if low.startswith("timestamp"):
            meta_columns["timestamp"] = i
        elif "name" in low:
            meta_columns["name"] = i
        elif "email" in low:
            meta_columns["email"] = i
        elif "how long" in low:
            meta_columns["duration"] = i
        elif "problems" in low:
            meta_columns["problems"] = i

    if unknown:
        raise TidyError(
            "form species not present in the canonical 41 "
            f"({', '.join(sorted(unknown))}). Add an alias to FORM_NAME_ALIASES "
            "or fix focal_species.json -- do not let a species drop silently."
        )
    if not species_columns:
        raise TidyError(
            f"no species columns detected in {csv_path}. Expected headers like "
            "'European Shag [1/41]'."
        )

    seen_codes = Counter(code for _, code in species_columns)
    dupes = sorted(c for c, n in seen_codes.items() if n > 1)
    if dupes:
        raise TidyError(f"the export maps two columns to the same species: {dupes}")

    respondents: list[dict] = []
    for row in rows[1:]:
        if not any((c or "").strip() for c in row):
            continue  # blank spacer row
        row = row + [""] * (len(header) - len(row))  # tolerate short rows

        def get(key: str) -> str:
            idx = meta_columns.get(key)
            return (row[idx].strip() if idx is not None and idx < len(row) else "")

        respondents.append(
            {
                "timestamp": get("timestamp"),
                "name": get("name"),
                "email": get("email"),
                "duration": get("duration"),
                "problems": get("problems"),
                "answers": {code: (row[i] or "").strip() for i, code in species_columns},
            }
        )

    return respondents, species_columns


def split_habitats(raw: str, label_to_slug: dict[str, str], context: str) -> tuple[list[str], bool]:
    """Split one answer cell into (slugs, dont_know).

    Habitat labels themselves contain commas ("Mountain, heath and bog"), so a
    naive split on "," is wrong. Match known labels longest-first instead.
    """
    text = (raw or "").strip()
    if not text:
        return [], False

    dont_know = False
    remaining = text
    if _norm(DONT_KNOW) in _norm(remaining):
        dont_know = True
        remaining = re.sub(re.escape(DONT_KNOW), "", remaining, flags=re.I)

    slugs: list[str] = []
    # Longest labels first so "Mountain, heath and bog" is consumed before any
    # shorter label that might be a substring of it.
    for label in sorted(label_to_slug, key=len, reverse=True):
        pattern = re.compile(re.escape(label), re.I)
        norm_remaining = _norm(remaining)
        if pattern.search(norm_remaining):
            slug = label_to_slug[label]
            if slug not in slugs:
                slugs.append(slug)
            # Remove every occurrence so leftovers can be validated below.
            remaining = pattern.sub("|", _norm(remaining))

    leftover = [t for t in re.split(r"[|,]", _norm(remaining)) if t.strip()]
    if leftover:
        raise TidyError(
            f"unrecognised habitat label(s) {leftover} in {context} (raw: {raw!r}). "
            "The 9 categories are frozen; add an alias to EXTRA_LABEL_ALIASES if "
            "the form wording drifted."
        )

    return slugs, dont_know


def respondent_column_names(respondents: list[dict]) -> list[str]:
    """Stable, unique, human-readable column name per respondent."""
    names: list[str] = []
    used: Counter = Counter()
    for i, r in enumerate(respondents, 1):
        base = r["name"].strip() or r["email"].strip() or f"respondent_{i}"
        used[base] += 1
        names.append(base if used[base] == 1 else f"{base} ({used[base]})")
    return names


def write_outputs(
    respondents: list[dict],
    outdir: str,
    slugs: list[str],
    slug_to_label: dict[str, str],
    label_to_slug: dict[str, str],
    write_long: bool = False,
) -> dict[str, str]:
    species = fs.load_species()
    columns = respondent_column_names(respondents)
    os.makedirs(outdir, exist_ok=True)

    # Parse every answer once, failing loudly on unknown labels.
    parsed: dict[str, list[tuple[list[str], bool]]] = {}
    for s in species:
        code = s["ebird_code"]
        per_respondent = []
        for r, col in zip(respondents, columns):
            raw = r["answers"].get(code, "")
            per_respondent.append(
                split_habitats(raw, label_to_slug, context=f"{s['common_name']} / {col}")
            )
        parsed[code] = per_respondent

    def display_name(s: dict) -> str:
        return s.get("red_list_name") or s.get("common_name", "")

    wide_path = os.path.join(outdir, "expert_responses_wide.csv")
    with open(wide_path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["ebird_code", "species"] + columns)
        for s in species:
            code = s["ebird_code"]
            cells = []
            for picks, dk in parsed[code]:
                labels = [slug_to_label[sl] for sl in picks]
                if dk:
                    labels.append(DONT_KNOW)
                cells.append(", ".join(labels))
            w.writerow([code, display_name(s)] + cells)

    long_path = os.path.join(outdir, "expert_responses_long.csv")
    if write_long:
        with open(long_path, "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(
                ["ebird_code", "species", "respondent", "category_slug", "category_label", "dont_know"]
            )
            for s in species:
                code = s["ebird_code"]
                for col, (picks, dk) in zip(columns, parsed[code]):
                    if dk and not picks:
                        w.writerow([code, display_name(s), col, "", "", "TRUE"])
                    for sl in picks:
                        w.writerow(
                            [code, display_name(s), col, sl, slug_to_label[sl], "TRUE" if dk else "FALSE"]
                        )

    matrix_path = os.path.join(outdir, "expert_responses_matrix.csv")
    with open(matrix_path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(
            ["ebird_code", "species"]
            + [slug_to_label[sl] for sl in slugs]
            + ["n_respondents", "n_dont_know"]
        )
        for s in species:
            code = s["ebird_code"]
            per = parsed[code]
            counts = [sum(1 for picks, _ in per if sl in picks) for sl in slugs]
            n_answered = sum(1 for picks, dk in per if picks or dk)
            n_dk = sum(1 for _, dk in per if dk)
            w.writerow([code, display_name(s)] + counts + [n_answered, n_dk])

    paths = {"wide": wide_path, "matrix": matrix_path}
    if write_long:
        paths["long"] = long_path
    return paths


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", help="Google Form export (default: newest CSV in code/expert_responses/)")
    ap.add_argument("--outdir", default=DEFAULT_OUTDIR, help=f"output directory (default: {DEFAULT_OUTDIR})")
    ap.add_argument(
        "--long",
        action="store_true",
        help="also write the long (one-row-per-tick) file; off by default. Use it "
             "when joining to the eBird presence matrices on category_slug.",
    )
    ap.add_argument(
        "--no-long",
        dest="long",
        action="store_false",
        help="explicitly skip the long file (this is already the default)",
    )
    args = ap.parse_args()

    csv_path = args.csv or find_default_csv()
    slugs, slug_to_label, label_to_slug = load_categories()
    _, species_lookup = build_species_lookup()

    respondents, species_columns = parse_export(csv_path, species_lookup)
    if not respondents:
        raise TidyError(f"{csv_path} has a header but no response rows.")

    paths = write_outputs(
        respondents, args.outdir, slugs, slug_to_label, label_to_slug, write_long=args.long
    )

    canonical = {s["ebird_code"] for s in fs.load_species()}
    covered = {code for _, code in species_columns}
    missing = canonical - covered

    print(f"input   : {csv_path}")
    print(f"parsed  : {len(respondents)} respondent(s), {len(species_columns)}/41 species columns")
    for r, col in zip(respondents, respondent_column_names(respondents)):
        note = f", took {r['duration']}" if r["duration"] else ""
        print(f"          - {col} ({r['timestamp']}{note})")
    if missing:
        names = fs.load_code_to_name()
        print(f"WARNING : {len(missing)} canonical species absent from the form, "
              f"emitted blank: {', '.join(sorted(names[c] for c in missing))}")
    print("outputs :")
    for kind in ("wide", "matrix", "long"):
        if kind in paths:
            print(f"          {kind:<7} {paths[kind]}")
    if "long" not in paths:
        print("          (long file skipped; pass --long to write it)")


if __name__ == "__main__":
    try:
        main()
    except (TidyError, fs.FocalSpeciesError) as exc:
        sys.exit(f"error: {exc}")
