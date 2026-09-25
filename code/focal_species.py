#!/usr/bin/env python3
"""focal_species.py  --  loader for the canonical 41-species study set
======================================================================

`code/focal_species.json` is the SINGLE SOURCE OF TRUTH for which species the
study covers. Every consumer -- the eBird land-cover analysis (scripts 15/16),
the RSPB Handbook coding, the LLM study and the expert survey -- reads the same
41 species from here, so the sources cannot drift apart.

Order is significant: script 15 sorts its outputs by this order and the
downstream matrices are row-aligned to it. `load_codes()` therefore preserves
file order.

Do NOT use `code/ebirdst/bocc_birds/red_list.json` (70 name-only BoCC entries)
or the `red_list_available` group in `code/ebirdst/species_list.json`
(50-species availability set) as a species source -- neither is the study set.

Usage
-----
    import sys, os
    sys.path.insert(0, os.path.join(HERE, ".."))   # the code/ directory
    import focal_species as fs

    codes = fs.load_codes()            # 41 eBird codes, in canonical order
    names = fs.load_code_to_name()     # {code: common_name}
    rows  = fs.load_species()          # full records

Run it directly for a summary:

    python code/focal_species.py
"""

from __future__ import annotations

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
FOCAL_SPECIES_JSON = os.path.join(HERE, "focal_species.json")

EXPECTED_COUNT = 41


class FocalSpeciesError(RuntimeError):
    """Raised when the canonical species file is missing or malformed."""


def _load_doc(path: str | None = None) -> dict:
    p = path or FOCAL_SPECIES_JSON
    if not os.path.exists(p):
        raise FocalSpeciesError(
            f"canonical species file not found at {p}. It is the single source of "
            "truth for the 41 focal species and must not be gitignored."
        )
    with open(p, "r", encoding="utf-8") as fh:
        doc = json.load(fh)

    species = doc.get("species")
    if not isinstance(species, list):
        raise FocalSpeciesError(f"{p} has no 'species' list.")

    # Fail loudly rather than letting a drifted roster through.
    if len(species) != EXPECTED_COUNT:
        raise FocalSpeciesError(
            f"expected exactly {EXPECTED_COUNT} focal species but {p} has "
            f"{len(species)}. The study set is fixed; fix the file rather than "
            "the assertion -- downstream matrices are row-aligned to it."
        )
    declared = doc.get("count")
    if declared is not None and int(declared) != len(species):
        raise FocalSpeciesError(
            f"{p} declares count={declared} but lists {len(species)} species."
        )

    codes = [s.get("ebird_code") for s in species]
    if any(not c for c in codes):
        raise FocalSpeciesError(f"{p} has a species entry with no ebird_code.")
    if len(set(codes)) != len(codes):
        dupes = sorted({c for c in codes if codes.count(c) > 1})
        raise FocalSpeciesError(f"{p} has duplicate ebird_code(s): {dupes}")

    return doc


def load_species(path: str | None = None) -> list[dict]:
    """The 41 full species records, in canonical order."""
    return _load_doc(path)["species"]


def load_codes(path: str | None = None) -> list[str]:
    """The 41 eBird codes, in canonical order (order is significant)."""
    return [s["ebird_code"] for s in load_species(path)]


def load_code_to_name(path: str | None = None) -> dict[str, str]:
    """{ebird_code: common_name} for the 41 focal species."""
    return {s["ebird_code"]: s.get("common_name", "") for s in load_species(path)}


def load_code_to_red_list_name(path: str | None = None) -> dict[str, str]:
    """{ebird_code: British vernacular}, falling back to common_name.

    This is the name shown to the model in the LLM study and used for RSPB
    Handbook coding (e.g. "Slavonian grebe", not eBird's "Horned Grebe").
    """
    return {
        s["ebird_code"]: (s.get("red_list_name") or s.get("common_name", ""))
        for s in load_species(path)
    }


def main() -> None:
    doc = _load_doc()
    species = doc["species"]
    print(f"{doc.get('name')}: {len(species)} species")
    print(f"  {doc.get('provenance', '')}")
    n_sci = sum(1 for s in species if s.get("scientific_name"))
    print(f"  scientific names resolved: {n_sci}/{len(species)}")
    print()
    for i, s in enumerate(species, 1):
        british = s.get("red_list_name")
        suffix = f"  [{british}]" if british else ""
        print(
            f"  {i:>2}. {s['ebird_code']:<9} {s.get('common_name','')}"
            f"{suffix}  ({s.get('scientific_name') or 'scientific name unresolved'})"
        )


if __name__ == "__main__":
    main()
