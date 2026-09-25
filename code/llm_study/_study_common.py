#!/usr/bin/env python3
"""_study_common.py  --  shared plumbing for the LLM parameter study
====================================================================

Paths, config loading, the 9 canonical habitat categories, the species roster,
and the prompt-template loader. Imported by run_study.py, parse.py and
aggregate.py so all three agree on the grid, the categories and the cell key.

Conventions here are deliberately copied from
`code/habitat_agents/_agent_common.py` (worktree-aware paths, the fenced-block
prompt loader, .env loading) so this module drops into the same repo without
introducing a second, competing set of idioms. That file is NOT imported or
modified -- this module stands alone.
"""

from __future__ import annotations

import csv
import json
import os
import re
import sys
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Paths (worktree-aware -- copied from _agent_common.py:45-62)
# ---------------------------------------------------------------------------
# The big gitignored inputs/outputs live in the MAIN checkout's outputs/ tree.
# When this file runs from inside a `.claude/worktrees/<name>` copy, strip that
# suffix so we read the real species CSV and write to the real outputs/ dir
# rather than the worktree's empty one.
HERE = os.path.dirname(os.path.abspath(__file__))
CODE_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))  # holds code/ + outputs/
_m = re.search(r"(.*)/\.claude/worktrees/[^/]+$", CODE_ROOT)
DATA_ROOT = _m.group(1) if _m else CODE_ROOT

# Code and config resolve against THIS checkout (code lives here even in a
# worktree); only the gitignored data lives under DATA_ROOT.
REPO_ROOT = CODE_ROOT

DEFAULT_CONFIG_PATH = os.path.join(HERE, "config.yaml")

# Filenames written under the output dir.
RAW_CALLS_FILENAME = "raw_calls.jsonl"
PARSED_CALLS_FILENAME = "parsed_calls.jsonl"
RESULTS_LONG_FILENAME = "results_long.csv"
MANIFEST_FILENAME = "run_manifest.json"
SUMMARY_FILENAME = "SUMMARY.md"
MATRICES_DIRNAME = "matrices"


def code_path(rel: str) -> str:
    """Resolve a repo-relative path that lives with the CODE (this checkout)."""
    return os.path.join(REPO_ROOT, rel)


def data_path(rel: str) -> str:
    """Resolve a repo-relative path that lives with the DATA (main checkout)."""
    return os.path.join(DATA_ROOT, rel)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass
class ModelSpec:
    """One model tier from config.yaml."""

    key: str                      # "haiku" / "sonnet" / "opus"
    id: str                       # the API model string
    tier: str
    input_usd_per_mtok: float
    output_usd_per_mtok: float
    supports_temperature: bool = True

    def cost_usd(self, input_tokens: int, output_tokens: int) -> float:
        """Cost of one call from the per-model pricing table."""
        return (
            (input_tokens / 1_000_000.0) * self.input_usd_per_mtok
            + (output_tokens / 1_000_000.0) * self.output_usd_per_mtok
        )


@dataclass
class Config:
    raw: dict[str, Any]
    models: dict[str, ModelSpec]
    repeats: int
    temperature: float
    max_tokens: int
    species_source: str
    species_prompt_name_column: str
    species_expected_count: int
    prompts_dir: str
    categories_path: str
    output_dir: str
    tool_config: dict[str, Any]
    retry: dict[str, Any]
    concurrency: dict[str, Any]
    dry_run_estimate: dict[str, Any]
    synonyms: dict[str, list[str]] = field(default_factory=dict)
    ambiguous_terms: dict[str, list[str]] = field(default_factory=dict)


def load_config(path: str | None = None) -> Config:
    """Load and validate config.yaml."""
    import yaml

    cfg_path = path or DEFAULT_CONFIG_PATH
    if not os.path.exists(cfg_path):
        sys.exit(f"ERROR: config not found at {cfg_path}")
    with open(cfg_path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)

    models: dict[str, ModelSpec] = {}
    for key, m in (raw.get("models") or {}).items():
        missing = [
            k for k in ("id", "input_usd_per_mtok", "output_usd_per_mtok") if k not in m
        ]
        if missing:
            sys.exit(f"ERROR: model '{key}' in {cfg_path} is missing {missing}.")
        models[key] = ModelSpec(
            key=key,
            id=m["id"],
            tier=m.get("tier", key),
            input_usd_per_mtok=float(m["input_usd_per_mtok"]),
            output_usd_per_mtok=float(m["output_usd_per_mtok"]),
            supports_temperature=bool(m.get("supports_temperature", True)),
        )
    if not models:
        sys.exit(f"ERROR: no models defined in {cfg_path}.")

    species = raw.get("species") or {}
    paths = raw.get("paths") or {}

    return Config(
        raw=raw,
        models=models,
        repeats=int(raw.get("repeats", 3)),
        temperature=float(raw.get("temperature", 0.0)),
        max_tokens=int(raw.get("max_tokens", 2000)),
        species_source=species.get("source", ""),
        species_prompt_name_column=species.get("prompt_name_column", "red_list_name"),
        species_expected_count=int(species.get("expected_count", 41)),
        prompts_dir=paths.get("prompts_dir", "code/llm_study/prompts"),
        categories_path=paths.get("categories", "code/llm_study/categories.json"),
        output_dir=paths.get("output_dir", "outputs/llm_study"),
        tool_config=raw.get("tools") or {},
        retry=raw.get("retry") or {},
        concurrency=raw.get("concurrency") or {},
        dry_run_estimate=raw.get("dry_run_estimate") or {},
        synonyms=raw.get("synonyms") or {},
        ambiguous_terms=raw.get("ambiguous_terms") or {},
    )


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------

def load_categories(cfg: Config) -> tuple[list[str], dict[str, str]]:
    """Load the 9 frozen habitat slugs and labels.

    Returns (slugs_in_canonical_order, {slug: label}). The slug order IS the
    matrix column order; downstream scoring joins on these strings.
    """
    path = code_path(cfg.categories_path)
    if not os.path.exists(path):
        sys.exit(f"ERROR: categories file not found at {path}")
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    cats = data.get("categories") or []
    slugs = [c["slug"] for c in cats]
    labels = {c["slug"]: c["label"] for c in cats}
    if len(slugs) != 9:
        sys.exit(
            f"ERROR: expected 9 habitat categories in {path}, found {len(slugs)}. "
            "The 9-category scheme is fixed for this study."
        )
    return slugs, labels


def format_category_list(slugs: list[str], labels: dict[str, str]) -> str:
    """Newline-joined category names, for the {CATEGORIES} placeholder."""
    return "\n".join(labels[s] for s in slugs)


# ---------------------------------------------------------------------------
# Species roster
# ---------------------------------------------------------------------------

def load_species(cfg: Config) -> list[dict[str, str]]:
    """Load the study species roster from the canonical source, asserting count.

    The source is `code/focal_species.json` -- the single source of truth shared
    by the eBird analysis (scripts 15/16), the RSPB Handbook coding, this study
    and the expert survey. Reading it here is what keeps the four sources on the
    same 41 species.

    Returns rows shaped {species_code, common_name, red_list_name} so the rest of
    the harness (and the output matrices) keep the same column shape as every
    other matrix in the repo.

    A .csv source is still accepted for backwards compatibility, in which case
    only the id columns are read -- never habitat cells -- so the model is never
    handed the answer it is being asked for.
    """
    path = code_path(cfg.species_source)
    if not os.path.exists(path):
        # Fall back to the data tree for a legacy outputs/ CSV source.
        alt = data_path(cfg.species_source)
        if os.path.exists(alt):
            path = alt
        else:
            sys.exit(
                f"ERROR: species source not found at {path}\n"
                f"(config species.source = {cfg.species_source!r})"
            )

    roster: list[dict[str, str]] = []

    if path.endswith(".json"):
        # Canonical path: delegate to code/focal_species.py so the count/duplicate
        # assertions live in exactly one place.
        sys.path.insert(0, os.path.join(REPO_ROOT, "code"))
        try:
            import focal_species  # noqa: PLC0415 -- deliberately late/optional
        except ImportError:
            sys.exit(
                "ERROR: could not import code/focal_species.py, the loader for the "
                "canonical species file."
            )
        try:
            records = focal_species.load_species(path)
        except focal_species.FocalSpeciesError as e:
            sys.exit(f"ERROR: {e}")
        for s in records:
            code = s["ebird_code"]
            common = s.get("common_name", "")
            roster.append(
                {
                    "species_code": code,
                    "common_name": common,
                    # British vernacular where recorded, else the eBird name.
                    "red_list_name": s.get("red_list_name") or common,
                }
            )
    else:
        with open(path, "r", encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            wanted = ["species_code", "common_name", "red_list_name"]
            missing = [c for c in wanted if c not in (reader.fieldnames or [])]
            if missing:
                sys.exit(
                    f"ERROR: species source {path} is missing column(s) {missing}. "
                    f"Found: {reader.fieldnames}"
                )
            for row in reader:
                roster.append({c: row[c] for c in wanted})

    n = len(roster)
    if n != cfg.species_expected_count:
        sys.exit(
            f"ERROR: expected exactly {cfg.species_expected_count} species but the "
            f"source yielded {n}.\n"
            f"  source: {path}\n"
            "The study set is fixed. Fix code/focal_species.json (or "
            "species.expected_count in config.yaml) rather than letting the roster "
            "drift -- downstream scoring matrices are row-aligned to this roster."
        )

    codes = [r["species_code"] for r in roster]
    if len(set(codes)) != n:
        sys.exit(f"ERROR: duplicate species_code values in {path}.")
    blank = [
        r for r in roster
        if not r.get("species_code") or not r.get(cfg.species_prompt_name_column)
    ]
    if blank:
        sys.exit(f"ERROR: {len(blank)} species row(s) in {path} have a blank id/name.")

    return roster


def species_display_name(sp: dict[str, str], cfg: Config) -> str:
    """The species name shown to the model (British vernacular by default)."""
    return sp.get(cfg.species_prompt_name_column) or sp.get("common_name", "")


# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

# Placeholders the harness substitutes wherever they appear. A simple template
# may use only {SPECIES}.
PH_SPECIES = "{SPECIES}"
PH_CATEGORIES = "{CATEGORIES}"
PH_CATEGORY_DEFINITIONS = "{CATEGORY_DEFINITIONS}"

CATEGORY_DEFINITIONS_FILENAME = "category_definitions.md"


def load_prompt_body(md_path: str) -> str:
    """Return the prompt text from a template markdown file.

    Matches the existing repo convention (`_agent_common.load_prompt_template`):
    the markdown may document methodology in prose and embed the ACTUAL prompt
    in the first fenced ``` block -- only that block reaches the model. If the
    file has no fenced block, the whole file is the prompt, so a plain-text
    template the user drops in also works.

    The fence must start at the beginning of a line (MULTILINE `^`). Prose that
    mentions ``` inline -- e.g. "only the first ``` block is sent" -- must not be
    mistaken for the opening fence, which would capture documentation instead of
    the prompt.
    """
    with open(md_path, "r", encoding="utf-8") as fh:
        text = fh.read()
    m = re.search(r"^```[^\n]*\n(.*?)\n^```", text, flags=re.DOTALL | re.MULTILINE)
    return (m.group(1) if m else text).strip()


def load_prompt_manifest(prompts_dir: str) -> dict[str, dict[str, str]]:
    """Load prompts/manifest.csv -> {filename: {label, guidance_level}}.

    A template absent from the manifest defaults to label=filename stem and
    guidance_level="unspecified"; a missing manifest is not an error.
    """
    path = os.path.join(prompts_dir, "manifest.csv")
    out: dict[str, dict[str, str]] = {}
    if not os.path.exists(path):
        return out
    with open(path, "r", encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            fname = (row.get("filename") or "").strip()
            if not fname:
                continue
            out[fname] = {
                "label": (row.get("label") or "").strip(),
                "guidance_level": (row.get("guidance_level") or "").strip(),
            }
    return out


@dataclass
class PromptTemplate:
    prompt_id: str        # filename stem, used in output filenames
    filename: str
    label: str
    guidance_level: str
    body: str

    def render(self, species_name: str, categories_block: str, definitions: str) -> str:
        """Substitute placeholders.

        Uses str.replace, NOT str.format -- prompt bodies contain literal JSON
        braces and .format would raise or mangle them.
        """
        text = self.body.replace(PH_SPECIES, species_name)
        text = text.replace(PH_CATEGORIES, categories_block)
        text = text.replace(PH_CATEGORY_DEFINITIONS, definitions)
        return text


def load_prompt_templates(cfg: Config) -> list[PromptTemplate]:
    """Load EVERY template found in the prompts dir.

    Any .md file is a template, except the manifest and the optional
    category_definitions.md glossary.
    """
    pdir = code_path(cfg.prompts_dir)
    if not os.path.isdir(pdir):
        sys.exit(f"ERROR: prompts dir not found at {pdir}")

    manifest = load_prompt_manifest(pdir)
    templates: list[PromptTemplate] = []
    for fname in sorted(os.listdir(pdir)):
        if not fname.endswith(".md") or fname == CATEGORY_DEFINITIONS_FILENAME:
            continue
        stem = os.path.splitext(fname)[0]
        meta = manifest.get(fname, {})
        body = load_prompt_body(os.path.join(pdir, fname))
        if PH_SPECIES not in body:
            sys.exit(
                f"ERROR: prompt template {fname} does not contain the {PH_SPECIES} "
                "placeholder, so it cannot be filled per species."
            )
        templates.append(
            PromptTemplate(
                prompt_id=stem,
                filename=fname,
                label=meta.get("label") or stem,
                guidance_level=meta.get("guidance_level") or "unspecified",
                body=body,
            )
        )
    if not templates:
        sys.exit(f"ERROR: no prompt templates (*.md) found in {pdir}")
    return templates


def load_category_definitions(cfg: Config) -> str:
    """Optional per-category glossary for {CATEGORY_DEFINITIONS}; "" if absent."""
    path = os.path.join(code_path(cfg.prompts_dir), CATEGORY_DEFINITIONS_FILENAME)
    if not os.path.exists(path):
        return ""
    return load_prompt_body(path)


# ---------------------------------------------------------------------------
# Cell identity (resumability)
# ---------------------------------------------------------------------------

def cell_key(
    model_key: str, prompt_id: str, tools: str, species_code: str, repeat_index: int
) -> str:
    """The idempotency key for one call.

    A run is resumable because every completed cell is recovered from
    raw_calls.jsonl by this key and skipped.
    """
    return f"{model_key}|{prompt_id}|{tools}|{species_code}|{repeat_index}"


def load_dotenv_if_present() -> None:
    """Load the repo-root .env so ANTHROPIC_API_KEY is set.

    Looks in this checkout first, then the main checkout (a worktree has no .env
    of its own -- it is gitignored and lives only in the main checkout).
    """
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    for root in (REPO_ROOT, DATA_ROOT):
        candidate = os.path.join(root, ".env")
        if os.path.exists(candidate):
            load_dotenv(candidate)
            return


def ensure_output_dir(cfg: Config) -> str:
    """Create and return the absolute output dir."""
    out = data_path(cfg.output_dir)
    os.makedirs(out, exist_ok=True)
    return out
