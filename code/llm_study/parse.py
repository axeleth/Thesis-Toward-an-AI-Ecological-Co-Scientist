#!/usr/bin/env python3
"""parse.py  --  raw model response  ->  9-length boolean vector
================================================================

Deterministic, and deliberately SEPARATE from generation. It reads
`raw_calls.jsonl` (written by run_study.py) and writes `parsed_calls.jsonl`, so
the parser can be improved and re-run over an existing run at ZERO API cost.

One consistent method for structured and free-text answers alike:

  1. If the response contains valid JSON listing categories, use it.
  2. Else match against the nine category names, then the synonym map
     (case-insensitive, whole-word).
  3. If neither yields a confident mapping, flag the call `invalid`.

Ambiguity: "farmland" spans Arable AND Improved Grassland. When the text offers
no finer detail, it maps to BOTH and the call is flagged low-confidence for
review. If the text also names something arable-specific or grassland-specific,
that finer evidence wins and no ambiguity flag is raised.

Negation: a sentence that rules a habitat OUT ("not found in woodland", "avoids
farmland") must not register as presence. Negated spans are removed before
matching.

Usage
-----
    python code/llm_study/parse.py                 # parse the default run
    python code/llm_study/parse.py --self-test     # offline unit cases, no I/O
    python code/llm_study/parse.py --raw <path> --out <path>
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _study_common as sc  # noqa: E402

# ---------------------------------------------------------------------------
# Negation handling
# ---------------------------------------------------------------------------
# Cues that flip the meaning of what follows. We blank out the span from the cue
# to the next clause boundary so terms inside it are not counted as presence.
NEGATION_CUES = [
    r"not\s+(?:commonly\s+|typically\s+|usually\s+|generally\s+)?(?:found|present|associated|seen|recorded)",
    r"(?:is|are)\s+not\b",
    r"rarely\b",
    r"seldom\b",
    r"never\b",
    r"avoids?\b",
    r"absent\b",
    r"does\s+not\b",
    r"do\s+not\b",
    r"no\b(?=\s+(?:strong\s+)?(?:association|presence))",
    r"unlikely\b",
    r"except\b",
    r"other\s+than\b",
    r"rather\s+than\b",
    r"instead\s+of\b",
]
# A negated span ends at a clause boundary: . ; : newline, or a contrastive
# conjunction that starts a fresh (positive) clause.
_CLAUSE_END = r"(?:[.;:\n]|\bbut\b|\bhowever\b|\bthough\b|\balthough\b|\bwhereas\b|\bwhile\b)"

_NEG_RE = re.compile(
    r"(?:" + "|".join(NEGATION_CUES) + r")(.*?)(?=" + _CLAUSE_END + r"|$)",
    flags=re.IGNORECASE | re.DOTALL,
)

# Trailing-negation: a sentence whose SUBJECT lists habitats and whose PREDICATE
# then negates them, e.g.
#     "The other habitat types (woodland, arable, ...) are not typical habitats."
#     "Woodland, arable and built-up areas are not used by this species."
# The forward rule above cannot catch these -- the cue comes AFTER the names --
# so the whole sentence has to be dropped. Real model output does this often
# (it is the natural way to say "and not the rest"), and mis-scoring it inverts
# the answer, so it is worth handling explicitly.
_NEG_PREDICATE = (
    r"(?:are|is|were|was)\s+(?:not|never|rarely|seldom)\b"
    r"|(?:are|is)\s+(?:un|non-?)\w+"
    r"|(?:do|does|did)\s+not\b"
    r"|(?:not|never)\s+(?:typical|used|usual|suitable|frequented|occupied)"
)
_TRAILING_NEG_RE = re.compile(
    # A sentence (no internal sentence break) containing a negative predicate.
    r"[^.;:\n]*?(?:" + _NEG_PREDICATE + r")[^.;:\n]*",
    flags=re.IGNORECASE,
)


def strip_negated_spans(text: str) -> str:
    """Blank out spans governed by a negation cue, so they can't score presence.

    Two passes, because negation attaches on either side of the habitat names:
      forward  -- "not found in woodland"                    (cue then names)
      trailing -- "woodland and arable are not typical"      (names then cue)
    """
    cleaned = _TRAILING_NEG_RE.sub(" ", text or "")
    return _NEG_RE.sub(" ", cleaned)


# ---------------------------------------------------------------------------
# JSON extraction (step 1)
# ---------------------------------------------------------------------------

def extract_json(raw: str):
    """Best-effort parse of JSON from a model response.

    Tries a direct parse, then a ```json fence, then the outermost [...] / {...}
    span. Returns the parsed object, or None if nothing usable parses.
    Adapted from code/habitat_agents/_agent_common.py:extract_json_array.
    """
    if not raw or not raw.strip():
        return None

    candidates: list[str] = [raw.strip()]
    fence = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", raw, flags=re.DOTALL)
    if fence:
        candidates.append(fence.group(1).strip())
    arr = re.search(r"\[.*\]", raw, flags=re.DOTALL)
    if arr:
        candidates.append(arr.group(0))
    brace = re.search(r"\{.*\}", raw, flags=re.DOTALL)
    if brace:
        candidates.append(brace.group(0))

    for cand in candidates:
        try:
            return json.loads(cand)
        except (json.JSONDecodeError, TypeError):
            continue
    return None


_TRUEY = {"true", "yes", "y", "present", "1", "documented", "commonly found"}
_FALSEY = {"false", "no", "n", "absent", "0", "not established", "not found"}


def _norm(s: str) -> str:
    """Lowercase, collapse punctuation/whitespace -- for slug/label matching."""
    return re.sub(r"[^a-z0-9]+", " ", str(s or "").lower()).strip()


def categories_from_json(obj, slugs: list[str], labels: dict[str, str]):
    """Map a parsed JSON object to {slug: bool}, or None if it isn't category data.

    Handles the shapes models actually emit:
      ["Woodland", "Coastal"]                                  -> listed = present
      {"woodland": true, "coastal": false}                      -> explicit booleans
      {"habitats": [...]}                                       -> wrapper key
      [{"habitat": "woodland", "present": true}, ...]           -> per-habitat objects
      [{"habitat": "woodland", "classification": "Documented"}] -> repo's existing shape
    """
    lookup: dict[str, str] = {}
    for s in slugs:
        lookup[_norm(s)] = s
        lookup[_norm(labels[s])] = s

    result: dict[str, bool] = {}
    matched_any = False

    def note(key, value=True) -> None:
        nonlocal matched_any
        slug = lookup.get(_norm(key))
        if slug is None:
            return
        matched_any = True
        if isinstance(value, bool):
            present = value
        else:
            v = _norm(value)
            if v in {_norm(x) for x in _TRUEY}:
                present = True
            elif v in {_norm(x) for x in _FALSEY}:
                present = False
            else:
                present = True  # a bare mention in a list means "present"
        result[slug] = present

    if isinstance(obj, dict):
        # Unwrap a single wrapper key such as {"habitats": [...]}.
        if len(obj) == 1:
            only_val = next(iter(obj.values()))
            if isinstance(only_val, (list, dict)) and not lookup.get(
                _norm(next(iter(obj.keys())))
            ):
                return categories_from_json(only_val, slugs, labels)
        for k, v in obj.items():
            note(k, v)
    elif isinstance(obj, list):
        for item in obj:
            if isinstance(item, str):
                note(item, True)
            elif isinstance(item, dict):
                # per-habitat object: find the name field and the verdict field
                name = None
                for nk in ("habitat", "category", "name", "slug", "habitat_type"):
                    if nk in item:
                        name = item[nk]
                        break
                if name is None:
                    for k, v in item.items():
                        note(k, v)
                    continue
                verdict = None
                for vk in ("present", "value", "answer", "classification", "verdict", "found"):
                    if vk in item:
                        verdict = item[vk]
                        break
                note(name, True if verdict is None else verdict)

    if not matched_any:
        return None
    return {s: bool(result.get(s, False)) for s in slugs}


# ---------------------------------------------------------------------------
# Text matching (step 2)
# ---------------------------------------------------------------------------

def _plural_suffix(word: str) -> str:
    """Regex fragment matching common English plural forms of `word`.

    Model prose says "estuaries and mudflats" where the synonym list says
    "estuary"/"mudflat", so the final word of a term is matched with an optional
    plural ending: -s, -es, and y -> ies.
    """
    esc = re.escape(word)
    if re.search(r"[^aeiou]y$", word, flags=re.IGNORECASE):
        return re.escape(word[:-1]) + r"(?:y|ies)"
    if re.search(r"(?:s|x|z|ch|sh)$", word, flags=re.IGNORECASE):
        return esc + r"(?:es)?"
    return esc + r"(?:s)?"


def _term_present(term: str, text: str) -> bool:
    """Whole-word, case-insensitive containment of a possibly multi-word term.

    Only the FINAL word is pluralised ("gravel pit" -> "gravel pits"), which is
    where English puts the plural in these noun phrases.
    """
    words = [w for w in re.split(r"[\s\-]+", term.strip()) if w]
    if not words:
        return False
    parts = [re.escape(w) for w in words[:-1]] + [_plural_suffix(words[-1])]
    pattern = r"(?<![a-z0-9])" + r"[\s\-]+".join(parts) + r"(?![a-z0-9])"
    return re.search(pattern, text, flags=re.IGNORECASE) is not None


def categories_from_text(
    raw: str, slugs: list[str], labels: dict[str, str], synonyms: dict, ambiguous: dict
) -> tuple[dict[str, bool], bool, list[str]]:
    """Match category names, then synonyms, over negation-stripped text.

    Returns (vector, low_confidence, notes).
    """
    text = strip_negated_spans(raw or "")
    result = {s: False for s in slugs}
    notes: list[str] = []

    # (a) the nine category names themselves
    for s in slugs:
        if _term_present(labels[s], text) or _term_present(s.replace("_", " "), text):
            result[s] = True

    # (b) the synonym map
    for slug, terms in (synonyms or {}).items():
        if slug not in result:
            continue
        for term in terms or []:
            if _term_present(term, text):
                result[slug] = True
                break

    # (c) ambiguous terms -- only when no finer evidence was found for the
    #     categories they span. "farmland" alone -> BOTH + low-confidence.
    low_confidence = False
    for term, targets in (ambiguous or {}).items():
        if not _term_present(term, text):
            continue
        if any(result.get(t) for t in targets):
            continue  # finer detail already decided it; not ambiguous here
        for t in targets:
            result[t] = True
        low_confidence = True
        notes.append(
            f"ambiguous term {term!r} with no finer detail -> mapped to "
            f"{', '.join(targets)}; flagged for review"
        )

    return result, low_confidence, notes


# ---------------------------------------------------------------------------
# The one public entry point
# ---------------------------------------------------------------------------

def parse_response(
    raw: str, slugs: list[str], labels: dict[str, str], synonyms: dict, ambiguous: dict
) -> dict:
    """Convert one raw response into a 9-length boolean vector + flags.

    Returns {vector, invalid_flag, low_confidence_flag, parse_method, notes}.
    """
    notes: list[str] = []

    if not raw or not raw.strip():
        return {
            "vector": {s: False for s in slugs},
            "invalid_flag": True,
            "low_confidence_flag": False,
            "parse_method": "empty",
            "notes": ["empty response"],
        }

    # Step 1 -- JSON.
    obj = extract_json(raw)
    if obj is not None:
        vec = categories_from_json(obj, slugs, labels)
        if vec is not None:
            # Even in JSON, a bare "farmland" value needs the ambiguity rule.
            _, low_conf, amb_notes = categories_from_text(
                raw, slugs, labels, {}, ambiguous
            )
            if low_conf and not (vec.get("arable") or vec.get("improved_grassland")):
                for t in ambiguous.get("farmland", []):
                    vec[t] = True
                notes.extend(amb_notes)
            else:
                low_conf = False
            return {
                "vector": vec,
                "invalid_flag": False,
                "low_confidence_flag": low_conf,
                "parse_method": "json",
                "notes": notes,
            }

    # Step 2 -- names, then synonyms.
    vec, low_conf, text_notes = categories_from_text(
        raw, slugs, labels, synonyms, ambiguous
    )
    notes.extend(text_notes)

    # Step 3 -- nothing matched anywhere => no confident mapping.
    if not any(vec.values()):
        return {
            "vector": vec,
            "invalid_flag": True,
            "low_confidence_flag": False,
            "parse_method": "none",
            "notes": notes + ["no category or synonym matched"],
        }

    return {
        "vector": vec,
        "invalid_flag": False,
        "low_confidence_flag": low_conf,
        "parse_method": "text",
        "notes": notes,
    }


# ---------------------------------------------------------------------------
# File-level driver
# ---------------------------------------------------------------------------

def parse_file(raw_path: str, out_path: str, cfg: sc.Config) -> tuple[int, int, int]:
    """Parse every row of raw_calls.jsonl into parsed_calls.jsonl."""
    slugs, labels = sc.load_categories(cfg)
    if not os.path.exists(raw_path):
        sys.exit(
            f"ERROR: no raw calls at {raw_path}\nRun run_study.py first."
        )

    n = n_invalid = n_lowconf = 0
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(raw_path, "r", encoding="utf-8") as fin, open(
        out_path, "w", encoding="utf-8"
    ) as fout:
        for line in fin:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            parsed = parse_response(
                rec.get("raw_response") or "",
                slugs,
                labels,
                cfg.synonyms,
                cfg.ambiguous_terms,
            )
            # An errored call is invalid regardless of what the parser made of it.
            if rec.get("error"):
                parsed["invalid_flag"] = True
                parsed["parse_method"] = "api_error"

            out = dict(rec)
            out["parsed_vector"] = parsed["vector"]
            out["invalid_flag"] = parsed["invalid_flag"]
            out["low_confidence_flag"] = parsed["low_confidence_flag"]
            out["parse_method"] = parsed["parse_method"]
            out["parse_notes"] = parsed["notes"]
            fout.write(json.dumps(out, ensure_ascii=False) + "\n")

            n += 1
            n_invalid += bool(parsed["invalid_flag"])
            n_lowconf += bool(parsed["low_confidence_flag"])
    return n, n_invalid, n_lowconf


# ---------------------------------------------------------------------------
# Self-test (offline; no API, no files)
# ---------------------------------------------------------------------------

def self_test(cfg: sc.Config) -> int:
    """Unit cases covering both structured and free-text paths."""
    slugs, labels = sc.load_categories(cfg)
    syn, amb = cfg.synonyms, cfg.ambiguous_terms

    def run(raw):
        return parse_response(raw, slugs, labels, syn, amb)

    cases: list[tuple[str, str, dict]] = [
        (
            "clean JSON list",
            '["Woodland", "Coastal"]',
            {"true": {"woodland", "coastal"}, "method": "json", "invalid": False},
        ),
        (
            "JSON booleans",
            '{"woodland": true, "arable": false, "coastal": true}',
            {"true": {"woodland", "coastal"}, "method": "json", "invalid": False},
        ),
        (
            "JSON per-habitat objects (repo shape)",
            '[{"habitat":"freshwater","classification":"Documented"},'
            ' {"habitat":"woodland","classification":"Not established"}]',
            {"true": {"freshwater"}, "method": "json", "invalid": False},
        ),
        (
            "fenced JSON",
            'Here you go:\n```json\n["Saltwater"]\n```',
            {"true": {"saltwater"}, "method": "json", "invalid": False},
        ),
        (
            "free text, category names",
            "The Shag is commonly found in Coastal areas and Saltwater.",
            {"true": {"coastal", "saltwater"}, "method": "text", "invalid": False},
        ),
        (
            "free text, synonyms only",
            "This species favours estuaries and mudflats, and forages offshore.",
            {"true": {"coastal", "saltwater"}, "method": "text", "invalid": False},
        ),
        (
            "synonym: moorland -> mountain_heath_bog",
            "Breeds on upland moorland and heather bog.",
            {"true": {"mountain_heath_bog"}, "method": "text", "invalid": False},
        ),
        (
            "bare farmland -> BOTH + low confidence",
            "The Corn Bunting is a bird of farmland.",
            {
                "true": {"arable", "improved_grassland"},
                "method": "text",
                "invalid": False,
                "low_conf": True,
            },
        ),
        (
            "farmland WITH finer detail -> no ambiguity flag",
            "Found on farmland, specifically arable cropland with stubble.",
            {"true": {"arable"}, "method": "text", "invalid": False, "low_conf": False},
        ),
        (
            "negation is not presence",
            "It is not found in woodland; it prefers coastal cliffs.",
            {"true": {"coastal"}, "method": "text", "invalid": False},
        ),
        (
            # Regression: real Haiku output on p2_scoped. The model answered
            # Saltwater + Coastal, then listed every OTHER habitat in a trailing
            # negative sentence. Scoring those as present inverted the answer.
            "trailing negation: 'the others are not typical habitats'",
            "The Kittiwake is commonly found in:\n- Saltwater\n- Coastal\n\n"
            "The other habitat types (woodland, arable, grassland, "
            "mountain/heath/bog, freshwater, and built-up areas) are not "
            "typical habitats for Kittiwakes in the UK.",
            {"true": {"saltwater", "coastal"}, "method": "text", "invalid": False},
        ),
        (
            "trailing negation: 'X and Y are not used'",
            "Coastal cliffs are the stronghold. Woodland and arable land are "
            "not used by this species.",
            {"true": {"coastal"}, "method": "text", "invalid": False},
        ),
        (
            "garbage -> invalid",
            "I'm sorry, I don't have enough information to answer that.",
            {"true": set(), "method": "none", "invalid": True},
        ),
        (
            "empty -> invalid",
            "",
            {"true": set(), "method": "empty", "invalid": True},
        ),
    ]

    failures = 0
    for name, raw, expect in cases:
        got = run(raw)
        true_slugs = {s for s, v in got["vector"].items() if v}
        ok = True
        detail = []

        if "true" in expect and true_slugs != expect["true"]:
            ok = False
            detail.append(f"present={sorted(true_slugs)} expected={sorted(expect['true'])}")
        if "invalid" in expect and got["invalid_flag"] != expect["invalid"]:
            ok = False
            detail.append(f"invalid={got['invalid_flag']} expected={expect['invalid']}")
        if "method" in expect and got["parse_method"] != expect["method"]:
            ok = False
            detail.append(f"method={got['parse_method']} expected={expect['method']}")
        if "low_conf" in expect and got["low_confidence_flag"] != expect["low_conf"]:
            ok = False
            detail.append(
                f"low_conf={got['low_confidence_flag']} expected={expect['low_conf']}"
            )

        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
        if not ok:
            failures += 1
            for d in detail:
                print(f"          {d}")

    print(f"\n{len(cases) - failures}/{len(cases)} parser cases passed.")
    return 1 if failures else 0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", default=None, help="path to config.yaml")
    ap.add_argument("--raw", default=None, help="path to raw_calls.jsonl")
    ap.add_argument("--out", default=None, help="path to parsed_calls.jsonl")
    ap.add_argument(
        "--self-test", action="store_true", help="run offline unit cases and exit"
    )
    args = ap.parse_args()

    cfg = sc.load_config(args.config)

    if args.self_test:
        print("Parser self-test (offline, no API):\n")
        sys.exit(self_test(cfg))

    out_dir = sc.ensure_output_dir(cfg)
    raw_path = args.raw or os.path.join(out_dir, sc.RAW_CALLS_FILENAME)
    out_path = args.out or os.path.join(out_dir, sc.PARSED_CALLS_FILENAME)

    n, n_invalid, n_lowconf = parse_file(raw_path, out_path, cfg)
    rate = (n_invalid / n * 100.0) if n else 0.0
    print(f"Parsed {n} call(s) from {raw_path}")
    print(f"  invalid:        {n_invalid} ({rate:.1f}%)")
    print(f"  low-confidence: {n_lowconf}")
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
