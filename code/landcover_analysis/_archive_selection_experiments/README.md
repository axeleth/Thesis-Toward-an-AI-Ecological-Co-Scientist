# Archived selection-metric experiments

These four scripts were exploratory work done alongside the availability-corrected
selection ratio (`15_selection_ratio_correction.py`). They are **not part of the
active pipeline** — the shipped result is the SR ≥ 1 corrected presence matrix
from script 15, scored against the RSPB Handbook by script 16.

They are kept because each answers a question that is likely to be asked, and the
answers are worth showing even though none changed the final method.

Outputs live in `outputs/landcover_analysis/selection_corrected/_archive_experiments/`.
All four still run — paths were preserved when they were moved here.

---

## `17_sr_threshold_sweep.py` — is SR ≥ 1 the right cutoff?

Swept the selection-ratio threshold against the Handbook and compared three rule
families: a global cutoff, per-class cutoffs, and top-K by SR.

| Rule | Free params | In-sample F1 | Leave-one-out F1 |
|---|---:|---:|---:|
| Fixed t = 1.00 (shipped) | 0 | 0.501 | 0.501 |
| Best global t = 0.80 | 1 | 0.528 | **0.450** |
| Per-class thresholds | 9 | 0.592 | **0.437** |
| Top-K, k = 5 | 1 | 0.538 | 0.538 |

**Conclusion: keep SR ≥ 1.** Both tuned threshold rules score *worse than the
untuned default* under cross-validation — their in-sample gains are noise fitted
on 40 species. Optimised macro F1 rather than accuracy, because the Handbook lists
2.95 of 9 habitats per species, so "predict nothing" already scores 0.672 accuracy.

Also recorded a null baseline that matters: always naming the five commonest
Handbook habitats — ignoring the data entirely — scores **0.498**, statistically
tied with SR ≥ 1 (0.501). At aggregate-9 resolution, the threshold is not where the
remaining error lives.

## `18_ceiling_test.py` — is the ~0.5 ceiling the data or the ground truth?

Scored the blind LLM agent against the same Handbook, same species, same metric, to
test whether ~0.5 was simply the best anything could do when projecting the
Handbook's prose onto 9 land-cover classes.

| Source | Precision | Recall | F1 |
|---|---:|---:|---:|
| Naive (Pareto-80) | 0.485 | 0.496 | 0.468 |
| Corrected (SR ≥ 1) | 0.522 | 0.557 | 0.501 |
| Prevalence baseline | — | — | 0.498 |
| **Blind agent** | 0.862 | 0.646 | **0.699** |
| Oracle on the SR ranking | — | — | 0.729 |

**Conclusion: the ground truth is fine; the headroom belongs to the data.** The
agent reaches 0.699 (+0.198, bootstrap CI [+0.113, +0.284]), so the Handbook *is*
reproducible at this resolution. The oracle bound of 0.729 shows the SR ranking
already orders habitats about as well as the agent — no cutoff rule is extracting it.

Caveat: the agent is one model's knowledge, not a true ceiling, and if the Handbook
is in its training data this test is conservative toward the data.

## `19_occupied_range_availability.R` + `20_selection_ratio_occupied.py` — does a per-species denominator help?

Script 18 suggested the UK-wide availability denominator was the culprit (species
where the data over-called marine habitats worsened at 0.667 vs 0.290). Script 19
extracts per-species occupied-range denominators from the weekly TIFs (50/50
species, 4 occupancy thresholds); script 20 rescores against them.

| Denominator | Precision | Recall | F1 |
|---|---:|---:|---:|
| UK-wide (shipped) | 0.522 | 0.557 | **0.501** |
| Occupied-range | 0.532 | 0.542 | **0.493** |

**Conclusion: it does not help — and the reason is instructive.** −0.008 F1, CI
[−0.067, +0.052]. F1 falls *monotonically* as the range tightens (0.493 → 0.487 →
0.480 → 0.422), so this is not an untested threshold; the denominator genuinely
moved (TV distance from the UK-wide profile 0.256 → 0.343).

The failure is a **circularity**: the occupied range is defined by where the bird
is, so a specialist's habitat becomes a large share of its own denominator and
normalises itself away. Coastal is 1.61% of the UK but 21.3% of the Puffin's
occupied range — *because the Puffin is there*. Its coastal SR collapses 29.26 →
2.21 and saltwater 2.54 → **0.46**, dropping below the threshold. The correction
deletes exactly the association it should keep.

Gains went to species with a real range/UK mismatch and no dominant habitat
(Red-necked Phalarope +0.400, White-fronted Goose +0.356); losses to specialists
whose habitat *is* their range (Kittiwake −0.400, Puffin −0.333, Goldeneye −0.318).

**This rules out availability scaling as the explanation for the 0.501 → 0.699 gap.**

---

## Where that leaves the method

The shipped result stands: **SR ≥ 1 with the UK-wide denominator**. It is the
principled cut (used as much as available), needs no tuning, and nothing tested
here beats it out of sample. The gap to the agent's 0.699 remains open, and the
two candidates still standing are the abundance→use mapping (summed annual
abundance may be the wrong quantity) and the 9-class projection itself. Neither is
implicated by evidence yet.
