"""
Two new aggregate figures requested in the 19 Aug meeting:

  Fig 11  memory-only prompt x model interaction (the supervisor's "capable models
          exploit richer prompts" reading), a clean line plot, tools-off only.
  Fig 12  source-vs-source agreement heatmap (supervisor suggestion): pairwise F1 (Dice,
          symmetric) among Book, Expert, LLM (Sonnet P4 off), Data. Lower triangle.

Writes into "Results figures/". Reads wrapped for the intermittent mount EDEADLK.
"""
import time, os
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))  # repo root (holds code/ + outputs/)
OUT  = f"{BASE}/Results figures"
OUTP = f"{BASE}/outputs"
FEATURED = "sonnet__p4_engineered__tools-off"

HAB = ["woodland","arable","improved_grassland","seminat_grassland",
       "mountain_heath_bog","saltwater","freshwater","coastal","builtup"]
HAB_DISP = ["Woodland","Arable","Improved grassland","Semi-natural grassland",
            "Mountain, heath and bog","Saltwater","Freshwater","Coastal","Built-up"]
VOTE_COLS = [f"votes_{d}" for d in HAB_DISP]

def rd(path, **kw):
    for i in range(12):
        try: return pd.read_csv(path, **kw)
        except OSError as e:
            if getattr(e,"errno",None)==35 or "deadlock" in str(e).lower():
                time.sleep(0.4+0.3*i); continue
            raise
    raise RuntimeError(path)

cfg  = rd(f"{OUTP}/llm_study/config_scores.csv")
dvb  = rd(f"{OUTP}/landcover_analysis/selection_corrected/aggregate9_data_vs_book_matrix.csv").set_index("species_code")
feat = rd(f"{OUTP}/llm_study/matrices/{FEATURED}.csv").set_index("species_code")
exp  = rd(f"{OUTP}/expert_survey/species_consistency.csv").set_index("ebird_code")  # 7-expert

# ---------- Fig 11: memory-only prompt x model ----------
off = cfg[cfg.tools=="off"]
piv = off.pivot_table(index="model",columns="prompt",values="f1_vs_book")
piv = piv.reindex(index=["haiku","sonnet","opus"],
                  columns=["p2_scoped","p3_informed","p4_engineered"])
C = {"haiku":"#38a169","sonnet":"#2b6cb0","opus":"#805ad5"}
fig,ax=plt.subplots(figsize=(7.5,5.5))
x=[0,1,2]
for m in ["haiku","sonnet","opus"]:
    ax.plot(x,piv.loc[m].values,marker="o",lw=2.4,ms=9,color=C[m],label=m.title())
    for xi,yi in zip(x,piv.loc[m].values):
        ax.annotate(f"{yi:.3f}",(xi,yi),textcoords="offset points",xytext=(0,8),
                    ha="center",fontsize=8,color=C[m])
ax.set_xticks(x); ax.set_xticklabels(["P2 scoped","P3 informed","P4 engineered"])
ax.set_ylabel("F1 vs Handbook (memory only, tools off)")
ax.set_xlabel("Prompt design")
ax.set_title("Fig 11. Capable models exploit richer prompts\nHaiku stays flat; Sonnet jumps then plateaus; Opus climbs")
ax.set_ylim(0.5,0.8); ax.grid(alpha=0.25); ax.legend(title="Model")
fig.tight_layout(); fig.savefig(f"{OUT}/fig11_memory_only_prompt_model.png",dpi=140); plt.close(fig)

# ---------- Fig 12: source-vs-source agreement heatmap ----------
def bookv(c): return np.array([int(bool(dvb.loc[c][f"book_{h}"])) for h in HAB])
def datav(c): return np.array([int(bool(dvb.loc[c][f"data_{h}"])) for h in HAB])
def llmv(c):  return np.array([int(bool(feat.loc[c][h])) for h in HAB])
def expv(c):
    # 7-expert consensus: present if > 50% of opinionated respondents marked it
    if c not in exp.index: return None
    r = exp.loc[c]; opin = int(r["n_respondents"])
    if opin <= 0: return None
    return np.array([1 if int(r[v]) > opin/2 else 0 for v in VOTE_COLS])

getters = {"Book":bookv, "Expert":expv, "LLM\n(Sonnet P4)":llmv, "Data":datav}
labels = list(getters.keys())

def dice(a,b):
    tp=int(((a==1)&(b==1)).sum()); den=int(a.sum()+b.sum())
    return (2*tp/den) if den else np.nan

def pair_f1(gA,gB):
    vals=[]
    for c in dvb.index:
        if c not in feat.index: continue
        a=gA(c); b=gB(c)
        if a is None or b is None: continue
        v=dice(a,b)
        if not np.isnan(v): vals.append(v)
    return np.mean(vals) if vals else np.nan

n=len(labels); M=np.full((n,n),np.nan)
for i in range(n):
    for j in range(n):
        if j<=i:
            M[i,j]=1.0 if i==j else pair_f1(getters[labels[i]],getters[labels[j]])
fig,ax=plt.subplots(figsize=(6.8,5.8))
masked=np.ma.masked_invalid(M)
im=ax.imshow(masked,cmap="YlGnBu",vmin=0.3,vmax=1.0)
ax.set_xticks(range(n)); ax.set_xticklabels(labels,fontsize=9)
ax.set_yticks(range(n)); ax.set_yticklabels(labels,fontsize=9)
for i in range(n):
    for j in range(n):
        if j<=i and not np.isnan(M[i,j]):
            ax.text(j,i,f"{M[i,j]:.2f}",ha="center",va="center",
                    color="white" if M[i,j]>0.7 else "black",fontsize=11)
ax.set_title("Fig 12. Agreement between sources (mean per-species F1)\nEach source scored against every other, Handbook not privileged")
fig.colorbar(im,label="Mean F1 (Dice) agreement",shrink=0.8)
fig.tight_layout(); fig.savefig(f"{OUT}/fig12_source_agreement_heatmap.png",dpi=140); plt.close(fig)

# ---------- Fig 13: expert consistency (settled vs disputed) ----------
ec = exp.reset_index().dropna(subset=["jaccard"]).sort_values("jaccard",ascending=False)
state_col = {"settled":"#2f855a","disputed":"#dd6b20","uncertain":"#a0aec0","knowledge gap":"#e53e3e"}
colors = [state_col.get(s,"#718096") for s in ec.knowledge_state]
fig,ax=plt.subplots(figsize=(11,5))
xs=np.arange(len(ec))
ax.bar(xs,ec.jaccard,color=colors)
ax.axhline(0.5,ls="--",color="black",lw=1)
ax.set_xticks(xs); ax.set_xticklabels(ec.species,rotation=90,fontsize=6)
ax.set_ylabel("Inter-expert agreement (Jaccard)")
n_set=int((ec.knowledge_state=="settled").sum()); n_dis=int((ec.knowledge_state=="disputed").sum())
ax.set_title(f"Fig 13. Expert consistency across 7 respondents\n{n_set} settled, {n_dis} disputed (split at Jaccard 0.50); mean 0.54")
from matplotlib.patches import Patch
ax.legend(handles=[Patch(color=state_col["settled"],label="Settled"),
                   Patch(color=state_col["disputed"],label="Disputed")])
ax.set_ylim(0,1.05)
fig.tight_layout(); fig.savefig(f"{OUT}/fig13_expert_consistency.png",dpi=140); plt.close(fig)

print("Fig 11 (memory-only):")
print(piv.round(3).to_string())
print("\nFig 12 agreement matrix (lower triangle):")
print(pd.DataFrame(M,index=[l.replace(chr(10)," ") for l in labels],
                   columns=[l.replace(chr(10)," ") for l in labels]).round(3).to_string())
print("\nSaved Fig 11 and Fig 12 to", OUT)
