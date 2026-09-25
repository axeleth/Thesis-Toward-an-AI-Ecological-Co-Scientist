"""
Supervisor request: does the number of habitats a species is associated with
affect the LLM's and the expert's verdicts?

x-axis = species' TRUE breadth = number of habitats the RSPB Handbook (Book)
         marks present (0-9).
y-axis = per-species agreement with the Book (F1, and precision/recall split).

Series:
  - LLM  = best config, Opus / P4-engineered / tools-on, vs Book.
  - Expert = the one real respondent (Expert A), vs Book, on the species they answered.

Also: calibration plot, LLM asserted breadth vs true Book breadth.

Reads are wrapped in a retry because the workspace mount intermittently
raises EDEADLK ("Resource deadlock avoided").

Writes PNGs + a small CSV to outputs/landcover_analysis/selection_corrected/breadth/.
"""
import time, os
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy import stats

BASE = os.path.join(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")), "outputs")
OUT = f"{BASE}/landcover_analysis/selection_corrected/breadth"

HAB = ["woodland","arable","improved_grassland","seminat_grassland",
       "mountain_heath_bog","saltwater","freshwater","coastal","builtup"]
VOTE_COLS = ["votes_Woodland","votes_Arable","votes_Improved grassland",
             "votes_Semi-natural grassland","votes_Mountain, heath and bog",
             "votes_Saltwater","votes_Freshwater","votes_Coastal","votes_Built-up"]

def read_csv_retry(path, tries=12, **kw):
    for i in range(tries):
        try:
            return pd.read_csv(path, **kw)
        except OSError as e:
            if getattr(e, "errno", None) == 35 or "deadlock" in str(e).lower():
                time.sleep(0.5 + 0.3*i); continue
            raise
    raise RuntimeError(f"could not read {path} after {tries} tries")

# ---- load
book_df = read_csv_retry(f"{BASE}/landcover_analysis/selection_corrected/aggregate9_data_vs_book_matrix.csv")
llm_df  = read_csv_retry(f"{BASE}/llm_study/matrices/opus__p4_engineered__tools-on.csv")
exp_df  = read_csv_retry(f"{BASE}/expert_survey/species_consistency_real_only.csv")

book_df = book_df.set_index("species_code")
llm_df  = llm_df.set_index("species_code")
exp_df  = exp_df.set_index("ebird_code")

def vec_book(code):
    r = book_df.loc[code]
    return np.array([bool(r[f"book_{h}"]) for h in HAB], dtype=int)

def vec_llm(code):
    r = llm_df.loc[code]
    return np.array([bool(r[h]) for h in HAB], dtype=int)

def vec_expert(code):
    """returns (vector, answered_bool). answered=False if expert said I don't know."""
    if code not in exp_df.index:
        return None, False
    r = exp_df.loc[code]
    if int(r.get("n_dont_know", 0)) >= 1:
        return None, False
    v = np.array([int(r[c]) for c in VOTE_COLS], dtype=int)
    return v, True

def prf(pred, truth):
    tp = int(((pred==1)&(truth==1)).sum())
    fp = int(((pred==1)&(truth==0)).sum())
    fn = int(((pred==0)&(truth==1)).sum())
    prec = tp/(tp+fp) if (tp+fp) else np.nan
    rec  = tp/(tp+fn) if (tp+fn) else np.nan
    f1   = (2*tp)/(2*tp+fp+fn) if (2*tp+fp+fn) else np.nan
    return prec, rec, f1

rows = []
for code in book_df.index:
    if code not in llm_df.index:
        continue
    b = vec_book(code)
    l = vec_llm(code)
    e, answered = vec_expert(code)
    breadth = int(b.sum())
    lp, lr, lf = prf(l, b)
    if answered:
        ep, er, ef = prf(e, b)
        ebreadth = int(e.sum())
    else:
        ep = er = ef = np.nan; ebreadth = np.nan
    rows.append(dict(code=code, name=book_df.loc[code]["species"],
                     book_breadth=breadth, llm_breadth=int(l.sum()),
                     expert_breadth=ebreadth,
                     llm_prec=lp, llm_rec=lr, llm_f1=lf,
                     exp_prec=ep, exp_rec=er, exp_f1=ef,
                     expert_answered=answered))
df = pd.DataFrame(rows)
os.makedirs(OUT, exist_ok=True)
df.to_csv(f"{OUT}/breadth_vs_verdict_per_species.csv", index=False)

# ---- correlations
def report_corr(x, y, label):
    m = (~np.isnan(x)) & (~np.isnan(y))
    if m.sum() < 3:
        print(f"{label}: n<3"); return
    rho, p = stats.spearmanr(x[m], y[m])
    print(f"{label}: Spearman rho={rho:+.3f} (p={p:.3f}, n={m.sum()})")

print(f"Species: {len(df)}, expert answered: {int(df.expert_answered.sum())}")
print(f"Book breadth range {df.book_breadth.min()}-{df.book_breadth.max()}, "
      f"LLM mean breadth {df.llm_breadth.mean():.2f}, "
      f"expert mean breadth {df.expert_breadth.mean():.2f}")
report_corr(df.book_breadth.values.astype(float), df.llm_f1.values, "LLM F1 vs book breadth")
report_corr(df.book_breadth.values.astype(float), df.llm_prec.values, "LLM precision vs book breadth")
report_corr(df.book_breadth.values.astype(float), df.llm_rec.values, "LLM recall vs book breadth")
ed = df[df.expert_answered]
report_corr(ed.book_breadth.values.astype(float), ed.exp_f1.values, "Expert F1 vs book breadth")
report_corr(df.book_breadth.values.astype(float), df.llm_breadth.values.astype(float),
            "LLM asserted breadth vs book breadth")

# ---- binned means with 95% CI
def binned(sub, ycol):
    out = []
    for bval, g in sub.groupby("book_breadth"):
        y = g[ycol].dropna().values
        if len(y)==0: continue
        m = y.mean()
        if len(y) > 1:
            ci = stats.t.ppf(0.975, len(y)-1) * y.std(ddof=1)/np.sqrt(len(y))
        else:
            ci = 0.0
        out.append((bval, m, ci, len(y)))
    return np.array(out)

# ================= PLOT 1: F1 vs breadth, LLM + expert =================
fig, ax = plt.subplots(figsize=(8,5.5))
jit = lambda n: (np.random.RandomState(0).rand(n)-0.5)*0.18
# points
ax.scatter(df.book_breadth+jit(len(df)), df.llm_f1, s=42, alpha=0.45,
           color="#2b6cb0", label="LLM (Opus P4) vs Book, per species")
ax.scatter(ed.book_breadth+jit(len(ed)), ed.exp_f1, s=42, alpha=0.45,
           color="#c05621", marker="^", label="Expert vs Book, per species")
# binned means
bl = binned(df, "llm_f1")
be = binned(ed, "exp_f1")
ax.errorbar(bl[:,0], bl[:,1], yerr=bl[:,2], color="#2b6cb0", lw=2.2, marker="o",
            capsize=4, label="LLM mean per breadth (95% CI)")
ax.errorbar(be[:,0], be[:,1], yerr=be[:,2], color="#c05621", lw=2.2, marker="^",
            capsize=4, ls="--", label="Expert mean per breadth (95% CI)")
ax.set_xlabel("Species' true breadth = number of habitats the Handbook lists")
ax.set_ylabel("Per-species F1 vs Handbook")
ax.set_title("Do generalist species get easier verdicts?\nAgreement with the Handbook vs how many habitats the species uses")
ax.set_ylim(-0.05, 1.05); ax.grid(alpha=0.25); ax.legend(fontsize=8, loc="lower right")
fig.tight_layout(); fig.savefig(f"{OUT}/1_f1_vs_breadth.png", dpi=140); plt.close(fig)

# ================= PLOT 2: LLM precision & recall vs breadth =================
fig, ax = plt.subplots(figsize=(8,5.5))
bp = binned(df, "llm_prec"); br = binned(df, "llm_rec")
ax.scatter(df.book_breadth+jit(len(df)), df.llm_prec, s=30, alpha=0.30, color="#805ad5")
ax.scatter(df.book_breadth+jit(len(df)), df.llm_rec,  s=30, alpha=0.30, color="#38a169")
ax.errorbar(bp[:,0], bp[:,1], yerr=bp[:,2], color="#805ad5", lw=2.2, marker="o",
            capsize=4, label="Precision (mean, 95% CI)")
ax.errorbar(br[:,0], br[:,1], yerr=br[:,2], color="#38a169", lw=2.2, marker="s",
            capsize=4, label="Recall (mean, 95% CI)")
ax.set_xlabel("Species' true breadth = number of habitats the Handbook lists")
ax.set_ylabel("LLM (Opus P4) vs Handbook")
ax.set_title("Where the LLM slope comes from\nBoth rise with breadth; precision is the weak point on specialists")
ax.set_ylim(-0.05, 1.05); ax.grid(alpha=0.25); ax.legend(fontsize=9, loc="lower right")
fig.tight_layout(); fig.savefig(f"{OUT}/2_precision_recall_vs_breadth.png", dpi=140); plt.close(fig)

# ================= PLOT 3: calibration, asserted vs true breadth =================
fig, ax = plt.subplots(figsize=(6.5,6))
ax.scatter(df.book_breadth+jit(len(df)), df.llm_breadth+jit(len(df)),
           s=48, alpha=0.5, color="#2b6cb0", label="LLM (Opus P4)")
ax.scatter(ed.book_breadth+jit(len(ed)), ed.expert_breadth+jit(len(ed)),
           s=48, alpha=0.5, color="#c05621", marker="^", label="Expert")
lim = [0, 9]
ax.plot(lim, lim, color="grey", ls=":", label="perfect calibration (y = x)")
ax.set_xlim(0,7.5); ax.set_ylim(0,7.5)
ax.set_xlabel("True breadth (Handbook habitats)")
ax.set_ylabel("Asserted breadth (habitats the source marks present)")
ax.set_title("Does the source widen its answer for broad species?")
ax.grid(alpha=0.25); ax.legend(fontsize=9, loc="upper left")
fig.tight_layout(); fig.savefig(f"{OUT}/3_calibration_breadth.png", dpi=140); plt.close(fig)

print("\nWrote plots + CSV to", OUT)
print(df[["name","book_breadth","llm_breadth","llm_f1","exp_f1"]].to_string(index=False))
