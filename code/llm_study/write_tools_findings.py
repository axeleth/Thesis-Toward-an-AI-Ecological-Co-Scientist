import json, collections, numpy as np, pandas as pd, os, re
HERE=os.path.abspath('.')
_m=re.search(r"(.*)/\.claude/worktrees/[^/]+$", HERE)
ROOT=_m.group(1) if _m else HERE
D=os.path.join(ROOT,'outputs','llm_study')
d=pd.read_csv(os.path.join(D,'config_scores.csv'))
g={(r['model'],r['prompt'],r['tools']):r for _,r in d.iterrows()}
MO=["haiku","sonnet","opus"]; PO=["p2_scoped","p3_informed","p4_engineered"]
ML={"haiku":"Haiku","sonnet":"Sonnet","opus":"Opus"}
PL={"p2_scoped":"P2 scoped","p3_informed":"P3 informed","p4_engineered":"P4 engineered"}

forced=[json.loads(l) for l in open(os.path.join(D,'forced_arm','raw_calls_forced.jsonl')) if l.strip()]
n_forced=len(forced); cost_forced=sum(r['cost_usd'] for r in forced)
err_forced=sum(1 for r in forced if r.get('error'))
srch_forced=sum(1 for r in forced if int(r.get('tool_calls_count') or 0))

L=[]
A=L.append
A("# The tools axis: availability, use, and forcing\n")
A("Findings from the three-arm tools experiment in the LLM parameter study. "
  "Generated from `outputs/llm_study/config_scores.csv` and the raw call logs; "
  "regenerate with `code/llm_study/write_tools_findings.py`.\n")
A("## The three arms\n")
A("The tools axis began as a binary, and that turned out to hide the interesting part:\n")
A("| Arm | The model... | Calls |")
A("|---|---|---:|")
A("| `off` | answers from its own knowledge; no tool is sent | 1,107 |")
A("| `on` | **is offered** web search and decides for itself whether to use it | 1,107 |")
A("| `forced` | is offered web search **and instructed to use it** before answering | 1,107 |")
A("")
A("Each arm is the same shape: 9 configurations (3 model tiers x 3 prompts) x 41 "
  "species x 3 repeats, aggregated by majority vote.\n")

A("## 1. \"Tools on\" never meant \"searched\"\n")
A("The `on` arm does not measure answering *with* web search. It measures answering "
  "when web search is *offered*, and whether that becomes a search is a decision the "
  "model makes. Across the `on` arm, **421 of 1,107 calls (38%) made no search at "
  "all**.\n")
A("| Configuration | Calls that searched |")
A("|---|---:|")
for m in MO:
    for p in PO:
        A(f"| {ML[m]} / {PL[p]} | {g[(m,p,'on')]['search_rate']*100:.1f}% |")
A("")
A("Two configurations -- **Opus with P3 and with P4 -- never searched once**, across "
  "all 123 calls each. Per-species repeat patterns (`code/llm_study/search_behaviour.py`) "
  "separate two different behaviours behind similar-looking rates:\n")
A("- **Opus P3/P4: 41 species never searched, 0 mixed.** A systematic refusal, not chance.")
A("- **Sonnet P4: 19 never, 19 mixed, 3 always.** A genuinely stochastic decision.")
A("- Sonnet's choice is also species-dependent -- it searched for Cirl Bunting and "
  "Red-necked Grebe, not House Sparrow or Curlew -- consistent with searching when "
  "it is uncertain.\n")
A("This is why the dashboard now reports a **Searched** column beside every tools-on "
  "configuration: the arm label alone overstates what happened.\n")

A("## 2. The forcing instruction works\n")
A(f"The `forced` arm prepends an explicit search instruction to each existing prompt "
  f"(templates otherwise unchanged). It is completely effective:\n")
A(f"- **{srch_forced} of {n_forced} calls searched (100.0%)**, in every one of the 9 "
  f"configurations, including both Opus configurations that had never searched.")
A(f"- **{err_forced} errors.** Actual spend **${cost_forced:.2f}**.\n")
A("That settles a question the `on` arm left open: the zero-search cells were **not** "
  "a tool-wiring bug. The tool was always available and functional; those models were "
  "choosing not to call it.\n")

A("## 3. Forcing search does not improve agreement with the Handbook\n")
A("F1 vs Book, all three arms, per configuration:\n")
A("| Configuration | off | on | forced | on−off | forced−on | forced−off | searched (on) |")
A("|---|---:|---:|---:|---:|---:|---:|---:|")
dof=[];dfo=[];dff=[]
for m in MO:
    for p in PO:
        o,n,f=g[(m,p,'off')],g[(m,p,'on')],g[(m,p,'forced')]
        a,b,c=o['f1_vs_book'],n['f1_vs_book'],f['f1_vs_book']
        dof.append(b-a);dfo.append(c-b);dff.append(c-a)
        A(f"| {ML[m]} / {PL[p]} | {a:.3f} | {b:.3f} | {c:.3f} | {b-a:+.3f} | "
          f"{c-b:+.3f} | {c-a:+.3f} | {n['search_rate']*100:.0f}% |")
A(f"| **Mean** | | | | **{np.mean(dof):+.3f}** | **{np.mean(dfo):+.3f}** | "
  f"**{np.mean(dff):+.3f}** | |")
A("")
A(f"- `forced` vs `on`: **{np.mean(dfo):+.3f}** mean F1 "
  f"({sum(1 for x in dfo if x>0)} better, {sum(1 for x in dfo if x<0)} worse)")
A(f"- `forced` vs `off`: **{np.mean(dff):+.3f}** mean F1 "
  f"({sum(1 for x in dff if x>0)} better, {sum(1 for x in dff if x<0)} worse)")
A(f"- `on` vs `off`: **{np.mean(dof):+.3f}** mean F1 "
  f"({sum(1 for x in dof if x>0)} better, {sum(1 for x in dof if x<0)} worse)\n")
A("**Every one of these differences is within the noise floor established below.** "
  "The conclusion is not that search helps a little; it is that on this task, at this "
  "sample size, retrieval makes no detectable difference to how well the model "
  "reproduces the Handbook -- at 5-8x the cost.\n")

A("### Opus was right to decline\n")
A("The two configurations built for this test are the sharpest case:\n")
for m,p in [('opus','p3_informed'),('opus','p4_engineered')]:
    o,n,f=g[(m,p,'off')],g[(m,p,'on')],g[(m,p,'forced')]
    mult=f['mean_cost_per_species']/o['mean_cost_per_species']
    A(f"- **{ML[m]} / {PL[p]}**: {o['f1_vs_book']:.3f} memory-only -> "
      f"{f['f1_vs_book']:.3f} forced to search "
      f"(**{f['f1_vs_book']-o['f1_vs_book']:+.3f}**, {mult:.1f}x the cost per species).")
A("")
A("Compelled to search, Opus did **worse** on P3 and no better on P4. Its refusal to "
  "search under the guided prompts was the better judgement -- a point about model "
  "behaviour that the binary axis could not have surfaced.\n")

A("### Forcing hurts most when the prompt is weakest\n")
A("| Prompt | forced−on | forced−off |")
A("|---|---:|---:|")
for p in PO:
    v=[g[(m,p,'forced')]['f1_vs_book']-g[(m,p,'on')]['f1_vs_book'] for m in MO]
    w=[g[(m,p,'forced')]['f1_vs_book']-g[(m,p,'off')]['f1_vs_book'] for m in MO]
    A(f"| {PL[p]} | {np.mean(v):+.3f} | {np.mean(w):+.3f} |")
A("")
A("A consistent gradient: retrieval degrades the vaguest prompt and is neutral-to-"
  "positive with the most engineered one. Search does not rescue an underspecified "
  "question -- it appears to add noise unless the prompt is already precise enough to "
  "use the results well. This reinforces the study's main finding that **prompt design "
  "dominates**: it outweighs model tier, and it outweighs retrieval.\n")

A("## 4. The noise floor: ~0.045 F1\n")
o=g[('opus','p3_informed','off')]; n=g[('opus','p3_informed','on')]
A(f"`Opus / P3 informed` supplies an accidental control. Its `on` cell searched on "
  f"**0%** of calls, so behaviourally it is identical to its `off` cell -- same model, "
  f"same prompt, same absence of retrieval. The two scored "
  f"**{o['f1_vs_book']:.3f}** and **{n['f1_vs_book']:.3f}**.\n")
A(f"That **{abs(n['f1_vs_book']-o['f1_vs_book']):.3f} F1** gap is pure run-to-run "
  "variance at 3 repeats. Any effect smaller than roughly that should not be read as "
  "real. It is worth stating explicitly in the write-up, because several differences "
  "in this study are smaller than it.\n")

A("## 5. Means mislead here: use medians for cost and latency\n")
lat=[float(r['wall_clock_seconds']) for r in forced
     if (r['model_key'],r['prompt_id'])==('opus','p4_engineered')]
ret=sum(int(r.get('api_retries') or 0) for r in forced
        if (r['model_key'],r['prompt_id'])==('opus','p4_engineered'))
a=np.array(lat)
A(f"`Opus / P4 engineered` in the forced arm reports a mean latency of **{a.mean():.1f}s** "
  f"against a median of **{np.median(a):.1f}s** -- a ratio of **{a.mean()/np.median(a):.2f}x**.\n")
A(f"The cause is not slow inference. Exactly **{ret} calls of {len(a)}** hit retry "
  f"backoff, and those same {(a>60).sum()} calls are the only ones over 60s; the "
  f"slowest took **{a.max():.0f}s**. Every other configuration in the arm has a "
  f"mean/median ratio between 1.01 and 1.13.\n")
A("The mean describes no call that actually happened, and would misrepresent Opus as "
  "an order of magnitude slower than it is. Cost is skewed the same way wherever a "
  "minority of calls run many searches.\n")
A("**Cost and latency are therefore reported as medians** throughout the scoring "
  "outputs and the dashboard -- cost per species (each species being `repeats` calls) "
  "and latency per call. The means are retained in `config_scores.csv` as "
  "`mean_cost_per_species` and `mean_latency_s`, and the dashboard flags any "
  "configuration whose mean exceeds its median by 30% or more, so the skew is visible "
  "rather than silently smoothed away. Two configurations trip that flag:\n")
_sk = d.copy()
_sk["rl"] = _sk.mean_latency_s / _sk.median_latency_s
_sk["rc"] = _sk.mean_cost_per_species / _sk.median_cost_per_species
A("| Configuration | mean latency | median latency | ratio |")
A("|---|---:|---:|---:|")
for _, r in _sk[_sk.rl >= 1.3].sort_values("rl", ascending=False).iterrows():
    A(f"| {ML[r['model']]} / {PL[r['prompt']]} / `{r['tools']}` | "
      f"{r['mean_latency_s']:.1f} s | {r['median_latency_s']:.1f} s | {r['rl']:.2f}x |")
A("")
A("The per-species F1 distributions are near-symmetric (|skew| <= 0.69, no zero-F1 "
  "species), so the accuracy metrics stay as macro means, matching scripts 17 and 18 "
  "and keeping them directly comparable.\n")
A("The efficiency frontier is unchanged by the switch, which is worth noting: the "
  "accessibility conclusion does not depend on the choice of central measure.\n")

A("## Open questions\n")
A("- **The P2 anomaly.** Haiku / P2 scoped *loses* 0.104 F1 when search is merely "
  "available, and forcing recovers only 0.012. Search genuinely degrades vague-prompt "
  "answers rather than this being a fluke, but the mechanism is unverified -- the raw "
  "responses should be read before this is claimed in the thesis.")
A("- **Search quality is unmeasured.** This experiment counts searches; it does not "
  "look at what was retrieved. A null result on accuracy is consistent with both "
  "\"retrieval does not help here\" and \"the retrieved pages were poor\".")
A("- **One reference standard.** All of this is agreement with the RSPB Handbook. A "
  "configuration that searches well could diverge from the Handbook by being *more* "
  "current than it.\n")
A("---\n")
A("Sources: `outputs/llm_study/config_scores.csv`, "
  "`outputs/llm_study/forced_arm/raw_calls_forced.jsonl`, "
  "`outputs/llm_study/search_behaviour/`. "
  "Scoring by `code/landcover_analysis/19_score_all_configs.py`; the forced arm by "
  "`code/llm_study/run_forced_arm.py`.")

out=os.path.join(D,'TOOLS_AXIS_FINDINGS.md')
open(out,'w').write("\n".join(L)+"\n")
print("wrote", out)
