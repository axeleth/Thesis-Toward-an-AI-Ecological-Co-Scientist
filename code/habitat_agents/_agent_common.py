#!/usr/bin/env python3
"""_agent_common.py  --  shared plumbing for the blind habitat-presence agent
=============================================================================

`run_blind_agent.py` asks a stock LLM (no retrieval) which of the 9 UKCEH-
aggregate (Strategy 2) habitat categories each red-list species is "commonly
found in", one model call per species, and writes:

  1. a BINARY presence matrix in the exact column shape of the data matrix
     `outputs/landcover_analysis/redlist_aggregate9_1km_weighted/redlist_aggregate9_1km_weighted_presence_matrix.csv`
     (True only when the agent decisively establishes the species is commonly found
     in the habitat; everything else -- including "cannot say" -- is False), and
  2. a long-form verdicts JSON (one row per species x habitat) for audit.

(The former data-aware "sighted" agent has been removed; only the blind agent
remains.)

This module holds everything the runner uses: paths (worktree-aware),
the canonical 9 categories, the Claude/OpenAI backends, JSON parsing, the
species roster loader, and the output writers. The LLM plumbing uses a lazy
client import, `os.getenv` keys, and a BadRequestError retry that drops `temperature` for models that reject it.

The data matrix is the DATA-derived ground truth these agents will later be
compared against; nothing here reads its True/False cells, only its species id
columns, so the LLM never sees the answer.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from typing import Callable

# ---------------------------------------------------------------------------
# Paths (worktree-aware, copied from 13_aggregate9_1km_weighted_presence_matrix.py)
# ---------------------------------------------------------------------------
# The git-ignored CSV inputs live in the MAIN checkout's outputs/ tree. When this
# file runs from inside a `.claude/worktrees/<name>` copy, strip that suffix so we
# read/write the real outputs/ directory rather than the worktree's empty one.
HERE = os.path.dirname(os.path.abspath(__file__))
CODE_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))  # holds code/ + outputs/
_m = re.search(r"(.*)/\.claude/worktrees/[^/]+$", CODE_ROOT)
DATA_ROOT = _m.group(1) if _m else CODE_ROOT

# Repo root for .env / prompt-template resolution is this checkout (code lives here
# even in a worktree); only the big gitignored data lives under DATA_ROOT.
REPO_ROOT = CODE_ROOT
PROMPTS_DIR = os.path.join(REPO_ROOT, "code", "prompts")

_AGG9_DIR = os.path.join(
    DATA_ROOT, "outputs", "landcover_analysis", "redlist_aggregate9_1km_weighted"
)
PRESENCE_MATRIX_CSV = os.path.join(
    _AGG9_DIR, "redlist_aggregate9_1km_weighted_presence_matrix.csv"
)

OUTPUT_DIR = os.path.join(DATA_ROOT, "outputs", "habitat_agents")


# ---------------------------------------------------------------------------
# The 9 canonical UKCEH-aggregate (Strategy 2) habitat categories
# ---------------------------------------------------------------------------
# Slug order matches the data matrix's column order exactly, so the agent
# matrices are column-for-column comparable to it. Labels match
# 11_redlist_abundance_by_aggregate9_1km_weighted.R / the long CSV's
# category_label.
CATEGORIES = [
    "woodland",
    "arable",
    "improved_grassland",
    "seminat_grassland",
    "mountain_heath_bog",
    "saltwater",
    "freshwater",
    "coastal",
    "builtup",
]
CATEGORY_LABELS = {
    "woodland": "Woodland",
    "arable": "Arable",
    "improved_grassland": "Improved grassland",
    "seminat_grassland": "Semi-natural grassland",
    "mountain_heath_bog": "Mountain, heath and bog",
    "saltwater": "Saltwater",
    "freshwater": "Freshwater",
    "coastal": "Coastal",
    "builtup": "Built-up",
}

# ---------------------------------------------------------------------------
# Model / call configuration (matches demo_run_stage1.py)
# ---------------------------------------------------------------------------
CLAUDE_MODEL = "claude-sonnet-4-6"   # Anthropic, primary
OPENAI_MODEL = "gpt-4o"              # OpenAI, comparator (via --model gpt-4o)
DEFAULT_MODEL = CLAUDE_MODEL

TEMPERATURE = 0.0
MAX_TOKENS = 2000
JSON_RETRIES = 1   # 1 retry => 2 tries per species on a non-JSON response

# The presence matrix is BINARY for these agents: True/False only, no empty/Gap.
# A habitat is True ONLY when the agent can decisively determine the species is
# commonly found there; anything short of that decisive determination -- including
# "cannot confidently say" -- is False. ("Gap", meaning no DATA exists on the
# species' habitat, is a concept for a later section, not this one.)
#
# The two positive/negative classification labels the model returns:
#   "Documented"     -> the agent decisively establishes the species is found here.
#   "Not established" -> it cannot decisively establish that -> False.
VALID_CLASSIFICATIONS = ("Documented", "Not established")


# ---------------------------------------------------------------------------
# Prompt template loading (fenced-block extractor, from demo_run_stage1.py)
# ---------------------------------------------------------------------------

def load_prompt_template(md_path: str, required_placeholders: tuple[str, ...]) -> str:
    """Extract the first fenced ``` block from a prompt markdown and validate it.

    The markdown documents methodology, then embeds the actual prompt inside a
    fenced block; only that block reaches the model. Every placeholder in
    `required_placeholders` (e.g. "{SPECIES}") must be present, or we exit.
    """
    if not os.path.exists(md_path):
        sys.exit(f"ERROR: prompt template not found at {md_path}.")
    with open(md_path, "r", encoding="utf-8") as fh:
        text = fh.read()

    m = re.search(r"```[^\n]*\n(.*?)\n```", text, flags=re.DOTALL)
    if not m:
        sys.exit(
            f"ERROR: no fenced ``` block found in {md_path}; "
            "expected the prompt template inside a code fence."
        )
    template = m.group(1)
    for placeholder in required_placeholders:
        if placeholder not in template:
            sys.exit(
                f"ERROR: prompt template {md_path} is missing the {placeholder} "
                "placeholder."
            )
    return template


def format_habitat_list() -> str:
    """Render the 9 habitats as a slug-tagged block the model echoes back by slug."""
    lines = []
    for slug in CATEGORIES:
        lines.append(f"- slug: {slug}")
        lines.append(f"  habitat: {CATEGORY_LABELS[slug]}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Model backends (copied from demo_run_stage1.py)
# ---------------------------------------------------------------------------

def call_claude(prompt: str) -> str:
    """Call Claude (Anthropic). Reads ANTHROPIC_API_KEY from the environment."""
    import anthropic  # lazy so the OpenAI path doesn't need it

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        sys.exit(
            "ERROR: ANTHROPIC_API_KEY is not set. Add it to the repo-root .env "
            "(see code/API_KEY_SETUP.md) or export it in your shell."
        )
    client = anthropic.Anthropic(api_key=api_key)

    kwargs = dict(
        model=CLAUDE_MODEL,
        max_tokens=MAX_TOKENS,
        temperature=TEMPERATURE,
        messages=[{"role": "user", "content": prompt}],
    )
    try:
        resp = client.messages.create(**kwargs)
    except anthropic.BadRequestError as e:
        # Newer Claude models reject `temperature`; retry once without it.
        if "temperature" in str(e).lower():
            kwargs.pop("temperature", None)
            resp = client.messages.create(**kwargs)
        else:
            raise
    return "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")


def call_openai(prompt: str) -> str:
    """Call GPT-4o (OpenAI). Reads OPENAI_API_KEY from the environment."""
    from openai import OpenAI  # lazy

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        sys.exit(
            "ERROR: OPENAI_API_KEY is not set. Add it to the repo-root .env "
            "(see code/API_KEY_SETUP.md) or export it in your shell."
        )
    client = OpenAI(api_key=api_key)
    resp = client.chat.completions.create(
        model=OPENAI_MODEL,
        temperature=TEMPERATURE,
        max_tokens=MAX_TOKENS,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.choices[0].message.content or ""


def get_backend(model: str) -> tuple[str, Callable[[str], str]]:
    """Resolve a --model value to (canonical_model_name, backend_callable)."""
    m = model.lower()
    if m in ("claude", "sonnet", CLAUDE_MODEL.lower()):
        return CLAUDE_MODEL, call_claude
    if m in ("gpt-4o", "gpt4o", "openai", OPENAI_MODEL.lower()):
        return OPENAI_MODEL, call_openai
    sys.exit(
        f"ERROR: unknown model '{model}'. "
        f"Use '{CLAUDE_MODEL}' (or 'claude'/'sonnet') "
        f"or '{OPENAI_MODEL}' (or 'gpt-4o'/'openai')."
    )


# ---------------------------------------------------------------------------
# JSON extraction / validation (adapted from demo_run_stage1.py)
# ---------------------------------------------------------------------------

def extract_json_array(raw: str) -> list[dict] | None:
    """Best-effort parse of a JSON ARRAY of objects from a model response.

    Tries a direct parse, then a ```json fence, then the outermost [...] / {...}
    span. A lone object is wrapped into a one-element list. Returns None if
    nothing usable parses.
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
            obj = json.loads(cand)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(obj, list):
            dicts = [o for o in obj if isinstance(o, dict)]
            if dicts:
                return dicts
        elif isinstance(obj, dict):
            return [obj]
    return None


def _snap_enum(value: str, valid: tuple[str, ...]) -> str:
    """Snap a string to a canonical enum member by case-insensitive match."""
    v = str(value or "").strip()
    for cand in valid:
        if v.lower() == cand.lower():
            return cand
    return v


def normalise_verdict(obj: dict) -> dict:
    """Coerce a parsed verdict object into our schema.

    Keys: `habitat` (slug echo), `classification` (Documented|Not established),
    `citations`, `reasoning`.
    """
    out: dict = {}
    out["habitat"] = str(obj.get("habitat", "") or "").strip()

    out["classification"] = _snap_enum(obj.get("classification", ""), VALID_CLASSIFICATIONS)

    citations = obj.get("citations", [])
    if isinstance(citations, str):
        citations = [citations] if citations.strip() else []
    elif isinstance(citations, list):
        citations = [str(c).strip() for c in citations if str(c).strip()]
    else:
        citations = []
    out["citations"] = citations

    out["reasoning"] = str(obj.get("reasoning", "") or "").strip()
    return out


def verdict_to_cell(classification: str):
    """Map a verdict to a BINARY matrix cell (True/False only, no empty).

    True ONLY when the agent decisively establishes the species is commonly found
    in the habitat ("Documented"). EVERYTHING else is False -- "Not established",
    an unrecognised value, or a missing verdict all mean the agent could not
    decisively determine the species is there, which is exactly a False here.
    (There is no "unsure"/Gap cell in this section by design.)
    """
    c = str(classification or "").strip().lower()
    return c == "documented"


# ---------------------------------------------------------------------------
# Inputs: species roster + abundance shares
# ---------------------------------------------------------------------------

def load_species_roster() -> list[dict]:
    """Load species_code / common_name / red_list_name from the data matrix.

    The data matrix IS the roster: reading it guarantees the agent matrices have
    the same species, in the same order, so the later diff aligns row-for-row. We
    read ONLY the id columns, never the True/False habitat cells, so the model is
    never handed the answer.
    """
    import csv

    if not os.path.exists(PRESENCE_MATRIX_CSV):
        sys.exit(
            f"ERROR: presence matrix not found at {PRESENCE_MATRIX_CSV}.\n"
            "Run code/landcover_analysis/"
            "13_aggregate9_1km_weighted_presence_matrix.py first."
        )
    roster = []
    with open(PRESENCE_MATRIX_CSV, "r", encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            roster.append(
                {
                    "species_code": row["species_code"],
                    "common_name": row["common_name"],
                    "red_list_name": row["red_list_name"],
                }
            )
    return roster


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------

def write_presence_matrix(path: str, rows: list[dict]) -> None:
    """Write the binary presence matrix, same column shape as the data matrix.

    `rows` is a list of {species_code, common_name, red_list_name, <slug>: cell,...}
    where each cell is True or False (True only when the species is decisively
    commonly found in that habitat; everything else is False).
    """
    import csv

    os.makedirs(os.path.dirname(path), exist_ok=True)
    header = ["species_code", "common_name", "red_list_name"] + CATEGORIES
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=header)
        writer.writeheader()
        for r in rows:
            out = {k: r.get(k, "") for k in header}
            writer.writerow(out)


def write_verdicts_json(path: str, records: list[dict]) -> None:
    """Write the long-form per-(species, habitat) verdict detail for audit."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(records, fh, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Per-species assessment driver
# ---------------------------------------------------------------------------

def assess_species(
    backend: Callable[[str], str],
    prompt: str,
) -> tuple[dict[str, dict], str, bool]:
    """Call the model once for one species; parse an array of per-habitat verdicts.

    Returns (verdicts_by_slug, raw_response, parse_failed). Objects are matched to
    the 9 canonical habitat slugs; anything with an unrecognised slug is dropped.
    parse_failed is True only when NOTHING usable parsed after the retries.
    """
    valid_slugs = set(CATEGORIES)
    last_raw = ""
    for attempt in range(JSON_RETRIES + 1):
        last_raw = backend(prompt)
        arr = extract_json_array(last_raw)
        if arr is not None:
            by_slug: dict[str, dict] = {}
            for obj in arr:
                fields = normalise_verdict(obj)
                slug = fields.get("habitat", "")
                if slug in valid_slugs:
                    by_slug[slug] = fields
            if by_slug:
                return by_slug, last_raw, False
        if attempt < JSON_RETRIES:
            time.sleep(1.0)
    return {}, last_raw, True


def load_dotenv_if_present() -> None:
    """Load the repo-root .env so ANTHROPIC_API_KEY / OPENAI_API_KEY are set."""
    try:
        from dotenv import load_dotenv

        load_dotenv(os.path.join(REPO_ROOT, ".env"))
    except ImportError:
        pass
