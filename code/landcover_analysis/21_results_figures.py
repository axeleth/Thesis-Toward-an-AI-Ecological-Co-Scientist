"""
Generate every table and figure referenced in the v3 Results outline into one folder:
    "Results figures/" at the vault root.

Single-model reference is SONNET / P4-engineered / TOOLS-OFF (cost-efficient, on the
frontier). The blind agent (ceiling test) is a separate run and is left as-is.

Reads are wrapped in a retry (the mount intermittently raises EDEADLK).
"""
import time, os, re
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))  # repo root (holds code/ + outputs/)
OUT = f"{BASE}/Results figures"
OUTP = f"{BASE}/outputs"
os.makedirs(OUT, exist_ok=True)

FEATURED = "sonnet__p4_engineered__tools-off"
FEATURED_LABEL = "Sonnet P4 (tools-off)"

HAB = ["woodland","arable","improved_grassland","seminat_grassland",
       "mountain_heath_bog","saltwater","freshwater","coastal","builtup"]
HAB_DISP = ["Woodland","Arable","Improved grassland","Semi-natural grassland",
            "Mountain, heath and bog","Saltwater","Freshwater","Coastal","Built-up"]
DISP2KEY = {d: k for d, k in zip(HAB_DISP, HAB)}
VOTE_COLS = [f"votes_{d}" for d in HAB_DISP]

def rd(path, **kw):
    for i in range(12):
        try:
            return pd.read_csv(path, **kw)
        except OSError as e:
            if getattr(e, "errno", None) == 35 or "deadlock" in str(e).lower():
                time.sleep(0.4 + 0.3*i); continue
            raise
    raise RuntimeError(f"cannot read {path}")

def parse_disp_set(s):
    if not isinstance(s, str) or not s.strip():
        return set()
    return {DISP2KEY[p.strip()] for p in s.split(";") if p.strip() in DISP2KEY}

def jaccard(a, b):
    a, b = set(a), set(b)
    u = a | b
    return len(a & b) / len(u) if u else np.nan

def prf(pred, truth):
    pred, truth = np.array(pred), np.array(truth)
    tp = int(((pred==1)&(truth==1)).sum()); fp = int(((pred==1)&(truth==0)).sum())
    fn = int(((pred==0)&(truth==1)).sum())
    p = tp/(tp+fp) if tp+fp else np.nan
    r = tp/(tp+fn) if tp+fn else np.nan
    f = 2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else np.nan
    return p, r, f

# ---------- load ----------
cfg   = rd(f"{OUTP}/llm_study/config_scores.csv")
srch  = rd(f"{OUTP}/llm_study/search_behaviour/per_config.csv")
ceil  = rd(f"{OUTP}/landcover_analysis/selection_corrected/ceiling_test.csv")
dvb   = rd(f"{OUTP}/landcover_analysis/selection_corrected/aggregate9_data_vs_book_matrix.csv").set_index("species_code")
lve   = rd(f"{OUTP}/expert_survey/llm_vs_expert.csv")  # 7-expert consensus
feat  = rd(f"{OUTP}/llm_study/matrices/{FEATURED}.csv").set_index("species_code")
expdf = rd(f"{OUTP}/expert_survey/species_consistency.csv").set_index("ebird_code")  # 7-expert

C_MODEL = {"haiku":"#38a169","sonnet":"#2b6cb0","opus":"#805ad5"}
C_PROMPT = {"p2_scoped":"#e53e3e","p3_informed":"#dd6b20","p4_engineered":"#2b6cb0"}

# ---------- per-species vectors ----------
def book_vec(c): return np.array([int(bool(dvb.loc[c][f"book_{h}"])) for h in HAB])
def data_vec(c): return np.array([int(bool(dvb.loc[c][f"data_{h}"])) for h in HAB])
def feat_vec(c): return np.array([int(bool(feat.loc[c][h])) for h in HAB])
def exp_vec(c):
    # 7-expert consensus: habitat present if > 50% of opinionated respondents marked it
    if c not in expdf.index: return None
    r = expdf.loc[c]; opin = int(r["n_respondents"])
    if opin <= 0: return None
    return np.array([1 if int(r[v]) > opin/2 else 0 for v in VOTE_COLS])
agent_sets = {r.species_code: parse_disp_set(r.agent_habitats) for r in ceil.itertuples()}

species = list(dvb.index)
index_lines = []

# ================= TABLE 1: data vs book scores =================
tp=fp=fn=tn=0; per=[]
for c in species:
    b, d = book_vec(c), data_vec(c)
    p,r,f = prf(d,b); per.append((p,r,f))
    tp+=int(((d==1)&(b==1)).sum()); fp+=int(((d==1)&(b==0)).sum())
    fn+=int(((d==0)&(b==1)).sum()); tn+=int(((d==0)&(b==0)).sum())
macro = np.nanmean(np.array(per),axis=0)
micro_p=tp/(tp+fp); micro_r=tp/(tp+fn); micro_f=2*tp/(2*tp+fp+fn)
t1 = pd.DataFrame([
    {"averaging":"macro","precision":round(macro[0],3),"recall":round(macro[1],3),
     "f1":round(macro[2],3),"accuracy":round((tp+tn)/(9*len(species)),3)},
    {"averaging":"micro","precision":round(micro_p,3),"recall":round(micro_r,3),
     "f1":round(micro_f,3),"accuracy":round((tp+tn)/(9*len(species)),3)},
])
t1.to_csv(f"{OUT}/table1_data_vs_book_scores.csv",index=False)

# ================= FIG 1: data vs book per class =================
rows=[]
for j,h in enumerate(HAB):
    ctp=ctf=cfp=cfn=0
    for c in species:
        b,d=book_vec(c),data_vec(c)
        ctp+=int(d[j]==1 and b[j]==1); cfp+=int(d[j]==1 and b[j]==0); cfn+=int(d[j]==0 and b[j]==1)
    pr=ctp/(ctp+cfp) if ctp+cfp else 0; rc=ctp/(ctp+cfn) if ctp+cfn else 0
    rows.append((HAB_DISP[j],pr,rc))
pc=pd.DataFrame(rows,columns=["class","precision","recall"])
fig,ax=plt.subplots(figsize=(9,5))
x=np.arange(len(pc)); w=0.38
ax.bar(x-w/2,pc.precision,w,label="Precision",color="#2b6cb0")
ax.bar(x+w/2,pc.recall,w,label="Recall",color="#dd6b20")
ax.set_xticks(x); ax.set_xticklabels(pc["class"],rotation=35,ha="right",fontsize=8)
ax.set_ylabel("Data vs Handbook"); ax.set_ylim(0,1.05); ax.grid(axis="y",alpha=0.25)
ax.set_title("Fig 1. Where the occurrence data over- and under-calls, by habitat class")
ax.legend(); fig.tight_layout(); fig.savefig(f"{OUT}/fig1_data_vs_book_per_class.png",dpi=140); plt.close(fig)

# ================= FIG 2 + TABLE 5: ceiling test =================
# Computed here on the SAME 41 focal species and the SAME per-species-F1 macro
# definition as Table 1, so the "Corrected data" bar is identical to Table 1 by construction.
agent_df = rd(f"{OUTP}/habitat_agents/blind_presence_matrix.csv").set_index("species_code")
def agent_vec(c):
    if c not in agent_df.index: return None
    return np.array([int(bool(agent_df.loc[c][h])) for h in HAB])
book_counts = np.array([sum(int(book_vec(c)[j]) for c in species) for j in range(9)])
top5 = set(np.argsort(book_counts)[-5:])
prev_pred = np.array([1 if j in top5 else 0 for j in range(9)])
corr_f1s, prev_f1s, agent_f1s = [], [], []
for c in species:
    b = book_vec(c)
    corr_f1s.append(prf(data_vec(c), b)[2])
    prev_f1s.append(prf(prev_pred, b)[2])
    a = agent_vec(c)
    if a is not None: agent_f1s.append(prf(a, b)[2])
corr_m, prev_m, agent_m = np.nanmean(corr_f1s), np.nanmean(prev_f1s), np.nanmean(agent_f1s)
means={"Corrected data":corr_m,
       "Prevalence baseline\n(data-free)":prev_m,
       "Blind agent\n(knowledge only)":agent_m}
t5=pd.DataFrame([{"source":k.replace("\n"," "),"macro_f1":round(v,3),"n_species":len(species)}
                 for k,v in means.items()])
t5.to_csv(f"{OUT}/table5_ceiling_test.csv",index=False)
fig,ax=plt.subplots(figsize=(7,5))
cols=["#4a5568","#cbd5e0","#2f855a"]
ax.bar(list(means.keys()),list(means.values()),color=cols)
for i,(k,v) in enumerate(means.items()): ax.text(i,v+0.01,f"{v:.3f}",ha="center",fontsize=10)
ax.axhline(0.5,ls=":",color="grey")
ax.set_ylabel("Macro F1 vs Handbook"); ax.set_ylim(0,0.85)
ax.set_xticklabels(list(means.keys()),rotation=15,ha="center",fontsize=9)
ax.set_title(f"Fig 2b. The corrected data barely beats guessing ({corr_m:.2f} vs {prev_m:.2f});\n"
             f"an informed knowledge source reaches {agent_m:.2f} against the Handbook")
fig.tight_layout(); fig.savefig(f"{OUT}/fig2b_data_ceiling.png",dpi=140); plt.close(fig)
# 2-bar version for Part 1 (data vs baseline only; blind agent deferred to Part 2)
fig,ax=plt.subplots(figsize=(5.5,5))
ax.bar(["Corrected data","Prevalence baseline\n(data-free)"],[corr_m,prev_m],color=["#4a5568","#cbd5e0"])
for i,v in enumerate([corr_m,prev_m]): ax.text(i,v+0.008,f"{v:.3f}",ha="center",fontsize=10)
ax.axhline(0.5,ls=":",color="grey")
ax.set_ylabel("Macro F1 vs Handbook"); ax.set_ylim(0,0.7)
ax.set_title("Fig 2a. Data approach performance")
fig.tight_layout(); fig.savefig(f"{OUT}/fig2a_data_vs_baseline.png",dpi=140); plt.close(fig)
print(f"Ceiling (41 sp): corrected {corr_m:.3f} | prevalence {prev_m:.3f} | blind agent {agent_m:.3f}")

# ================= TABLE 3: config leaderboard =================
lead=cfg.sort_values("f1_vs_book",ascending=False)[[
    "model_label","prompt_label","tools","f1_vs_book","f1_vs_data","kappa_vs_book",
    "accuracy_vs_book","median_cost_per_species","median_latency_s","invalid_rate","on_frontier"]].copy()
for col in ["f1_vs_book","f1_vs_data","kappa_vs_book","accuracy_vs_book"]:
    lead[col]=lead[col].round(3)
lead["median_cost_per_species"]=lead["median_cost_per_species"].round(4)
lead["median_latency_s"]=lead["median_latency_s"].round(2)
lead["featured"]=(cfg.sort_values("f1_vs_book",ascending=False)["config_id"]==FEATURED).values
lead.to_csv(f"{OUT}/table3_config_leaderboard.csv",index=False)

# ================= FIG 3: model x prompt heatmap =================
piv=cfg.groupby(["model","prompt"]).f1_vs_book.mean().unstack()
piv=piv.reindex(index=["haiku","sonnet","opus"],columns=["p2_scoped","p3_informed","p4_engineered"])
fig,ax=plt.subplots(figsize=(7,4.5))
im=ax.imshow(piv.values,cmap="YlGnBu",vmin=0.5,vmax=0.8,aspect="auto")
ax.set_xticks(range(3)); ax.set_xticklabels(["P2 scoped","P3 informed","P4 engineered"])
ax.set_yticks(range(3)); ax.set_yticklabels(["Haiku","Sonnet","Opus"])
for i in range(3):
    for j in range(3):
        ax.text(j,i,f"{piv.values[i,j]:.3f}",ha="center",va="center",
                color="white" if piv.values[i,j]>0.68 else "black",fontsize=11)
ax.set_title("Fig 3. Mean F1 vs Handbook by model and prompt\n(prompt is the dominant lever)")
fig.colorbar(im,label="F1 vs Handbook",shrink=0.8); fig.tight_layout()
fig.savefig(f"{OUT}/fig3_model_prompt_heatmap.png",dpi=140); plt.close(fig)

# ================= TABLE 2 + FIG 4: search + tools axis =================
t2=srch[["model","prompt","pct_searched","mean_searches_per_call",
         "species_always_searched","species_never_searched","species_mixed"]].copy()
t2.to_csv(f"{OUT}/table2_search_rates.csv",index=False)
# delta on-off per model x prompt from config_scores
off=cfg[cfg.tools=="off"].set_index(["model","prompt"])
on =cfg[cfg.tools=="on"].set_index(["model","prompt"])
keys=[k for k in off.index if k in on.index]
dl=pd.DataFrame({
    "model":[k[0] for k in keys],"prompt":[k[1] for k in keys],
    "delta_f1":[on.loc[k].f1_vs_book-off.loc[k].f1_vs_book for k in keys],
    "cost_mult":[on.loc[k].median_cost_per_species/max(off.loc[k].median_cost_per_species,1e-6) for k in keys]})
fig,ax=plt.subplots(figsize=(8,5.5))
for _,r in dl.iterrows():
    ax.scatter(r.cost_mult,r.delta_f1,s=90,color=C_MODEL[r.model],
               marker={"p2_scoped":"o","p3_informed":"s","p4_engineered":"^"}[r.prompt])
ax.axhline(0,color="grey",lw=1); ax.axhline(0.045,ls=":",color="red"); ax.axhline(-0.045,ls=":",color="red")
ax.set_xscale("log"); ax.set_xlabel("Cost multiple of turning search on (log)")
ax.set_ylabel("F1 change vs Handbook (on minus off)")
ax.set_title("Fig 4. Web search costs 2-18x and does not move accuracy\n(dotted red = +/- noise floor)")
from matplotlib.lines import Line2D
leg=[Line2D([0],[0],marker='o',color='w',markerfacecolor=C_MODEL[m],label=m.title(),markersize=9) for m in C_MODEL]
leg+=[Line2D([0],[0],marker=mk,color='grey',label=lb,markersize=9,ls='') for mk,lb in
      [("o","P2"),("s","P3"),("^","P4")]]
ax.legend(handles=leg,fontsize=8,ncol=2); ax.grid(alpha=0.2)
fig.tight_layout(); fig.savefig(f"{OUT}/fig4_search_delta_vs_cost.png",dpi=140); plt.close(fig)

# ================= FIG 5: accuracy vs cost frontier =================
fig,ax=plt.subplots(figsize=(8.5,5.5))
for _,r in cfg.iterrows():
    ax.scatter(r.median_cost_per_species,r.f1_vs_book,s=70,alpha=0.8,color=C_MODEL[r.model],
               edgecolor="black" if r.on_frontier else "none",linewidth=1.4)
for _,r in cfg.iterrows():
    if r.config_id in (FEATURED,"opus__p4_engineered__tools-on"):
        ax.annotate(r.config_id.replace("__","\n"),(r.median_cost_per_species,r.f1_vs_book),
                    fontsize=7,xytext=(6,-4),textcoords="offset points")
ax.set_xscale("log"); ax.set_xlabel("Median cost per species (USD, log)")
ax.set_ylabel("F1 vs Handbook")
ax.set_title("Fig 5. Accuracy vs cost across 27 configs\n(black outline = efficiency frontier; a cheap Sonnet config nearly matches the top)")
leg=[Line2D([0],[0],marker='o',color='w',markerfacecolor=C_MODEL[m],label=m.title(),markersize=9) for m in C_MODEL]
ax.legend(handles=leg,fontsize=9); ax.grid(alpha=0.2)
fig.tight_layout(); fig.savefig(f"{OUT}/fig5_accuracy_vs_cost.png",dpi=140); plt.close(fig)

# ================= TABLE 4: pairwise Jaccard =================
def mean_jac(getA,getB,sp):
    vals=[]
    for c in sp:
        a,b=getA(c),getB(c)
        if a is None or b is None: continue
        vals.append(jaccard(np.where(a==1)[0],np.where(b==1)[0]))
    return round(np.nanmean(vals),3)
agent_get=lambda c:(np.array([1 if h in agent_sets.get(c,set()) else 0 for h in HAB]) if c in agent_sets else None)
t4=pd.DataFrame([
    {"pair":"Handbook vs Data","mean_jaccard":mean_jac(book_vec,data_vec,species)},
    {"pair":f"Handbook vs {FEATURED_LABEL}","mean_jaccard":mean_jac(book_vec,feat_vec,species)},
    {"pair":f"Data vs {FEATURED_LABEL}","mean_jaccard":mean_jac(data_vec,feat_vec,species)},
    {"pair":"Handbook vs Blind agent","mean_jaccard":mean_jac(book_vec,agent_get,species)},
    {"pair":"Data vs Blind agent","mean_jaccard":mean_jac(data_vec,agent_get,species)},
])
t4.to_csv(f"{OUT}/table4_pairwise_jaccard.csv",index=False)

# ================= TABLE 6: llm vs expert leaderboard =================
t6=lve.sort_values("f1_vs_expert",ascending=False)[[
    "model","prompt","tools","f1_vs_expert","jaccard_vs_expert","precision_vs_expert",
    "recall_vs_expert","f1_vs_book","baseline_breadth","n_species_scored"]].copy()
for c in ["f1_vs_expert","jaccard_vs_expert","precision_vs_expert","recall_vs_expert","f1_vs_book","baseline_breadth"]:
    t6[c]=t6[c].round(3)
t6.to_csv(f"{OUT}/table6_llm_vs_expert.csv",index=False)

# ================= FIG 6: breadth by config =================
lve2=lve.copy()
order=lve2.sort_values("baseline_breadth")
fig,ax=plt.subplots(figsize=(10,5))
xs=np.arange(len(order))
ax.bar(xs,order.baseline_breadth,color=[C_PROMPT[p] for p in order.prompt])
ax.axhline(2.10,ls="--",color="black"); ax.text(0.3,2.22,"expert consensus = 2.10",fontsize=9)
ax.set_xticks(xs); ax.set_xticklabels([f"{m[:3]}/{p.split('_')[0]}/{t}" for m,p,t in
                zip(order.model,order.prompt,order.tools)],rotation=90,fontsize=6)
ax.set_ylabel("Mean habitats asserted per species")
ax.set_title("Fig 6. Assertion breadth by configuration (expert consensus asserts ~2.1)")
leg=[Line2D([0],[0],marker='s',color='w',markerfacecolor=C_PROMPT[p],label=lb,markersize=10)
     for p,lb in [("p2_scoped","P2"),("p3_informed","P3"),("p4_engineered","P4")]]
ax.legend(handles=leg,fontsize=9); fig.tight_layout()
fig.savefig(f"{OUT}/fig6_breadth_by_config.png",dpi=140); plt.close(fig)

# ================= FIG 7: breadth vs expert agreement (r=-0.98) =================
from scipy import stats as st
r_p=st.pearsonr(lve.baseline_breadth,lve.f1_vs_expert)[0]
fig,ax=plt.subplots(figsize=(7.5,5.5))
for _,r in lve.iterrows():
    ax.scatter(r.baseline_breadth,r.f1_vs_expert,s=80,color=C_MODEL[r.model],
               marker={"p2_scoped":"o","p3_informed":"s","p4_engineered":"^"}[r.prompt],alpha=0.85)
m,b=np.polyfit(lve.baseline_breadth,lve.f1_vs_expert,1)
xr=np.linspace(lve.baseline_breadth.min(),lve.baseline_breadth.max(),50)
ax.plot(xr,m*xr+b,color="grey",ls="--")
ax.set_xlabel("Mean habitats asserted per species"); ax.set_ylabel("F1 vs expert")
ax.set_title(f"Fig 7. Saying less wins: assertion breadth vs expert agreement (Pearson r = {r_p:.2f})")
leg=[Line2D([0],[0],marker='o',color='w',markerfacecolor=C_MODEL[mm],label=mm.title(),markersize=9) for mm in C_MODEL]
ax.legend(handles=leg,fontsize=9); ax.grid(alpha=0.2)
fig.tight_layout(); fig.savefig(f"{OUT}/fig7_breadth_vs_expert.png",dpi=140); plt.close(fig)

# ================= FIG 8/9/10: per-species breadth, FEATURED model =================
rows=[]
for c in species:
    if c not in feat.index: continue
    b=book_vec(c); l=feat_vec(c); e=exp_vec(c)
    lp,lr,lf=prf(l,b)
    if e is not None: ep,er,ef=prf(e,b); eb=int(e.sum())
    else: ep=er=ef=np.nan; eb=np.nan
    rows.append(dict(code=c,book_breadth=int(b.sum()),llm_breadth=int(l.sum()),
                     expert_breadth=eb,llm_prec=lp,llm_rec=lr,llm_f1=lf,
                     exp_f1=ef,answered=(e is not None)))
bd=pd.DataFrame(rows); bd.to_csv(f"{OUT}/fig8_10_breadth_per_species.csv",index=False)
ed=bd[bd.answered]
def binned(sub,col):
    o=[]
    for v,g in sub.groupby("book_breadth"):
        y=g[col].dropna().values
        if len(y)==0: continue
        ci=st.t.ppf(0.975,len(y)-1)*y.std(ddof=1)/np.sqrt(len(y)) if len(y)>1 else 0
        o.append((v,y.mean(),ci))
    return np.array(o)
jit=lambda n:(np.random.RandomState(0).rand(n)-0.5)*0.18
# Fig 8 (LLM only; per supervisor feedback, just the model line, and expert-vs-book is not featured)
rho8,p8=st.spearmanr(bd.book_breadth,bd.llm_f1)
fig,ax=plt.subplots(figsize=(8,5.5))
ax.scatter(bd.book_breadth+jit(len(bd)),bd.llm_f1,s=48,alpha=0.5,color="#2b6cb0",label=f"{FEATURED_LABEL}, per species")
bl=binned(bd,"llm_f1")
ax.errorbar(bl[:,0],bl[:,1],yerr=bl[:,2],color="#2b6cb0",lw=2.4,marker="o",capsize=4,label="mean per breadth (95% CI)")
ax.set_xlabel("Species' true breadth (number of Handbook habitats)"); ax.set_ylabel("Per-species F1 vs Handbook")
ax.set_title(f"Fig 8. Does a species' breadth change the model's verdict?\nSpearman r = {rho8:.2f} (p = {p8:.2f}); at most a weak upward trend")
ax.set_ylim(-0.05,1.05); ax.grid(alpha=0.25); ax.legend(fontsize=9,loc="lower right")
fig.tight_layout(); fig.savefig(f"{OUT}/fig8_f1_vs_breadth.png",dpi=140); plt.close(fig)
# Fig 9
fig,ax=plt.subplots(figsize=(8,5.5))
bp=binned(bd,"llm_prec"); br=binned(bd,"llm_rec")
ax.scatter(bd.book_breadth+jit(len(bd)),bd.llm_prec,s=30,alpha=0.3,color="#805ad5")
ax.scatter(bd.book_breadth+jit(len(bd)),bd.llm_rec,s=30,alpha=0.3,color="#38a169")
ax.errorbar(bp[:,0],bp[:,1],yerr=bp[:,2],color="#805ad5",lw=2.2,marker="o",capsize=4,label="Precision (95% CI)")
ax.errorbar(br[:,0],br[:,1],yerr=br[:,2],color="#38a169",lw=2.2,marker="s",capsize=4,label="Recall (95% CI)")
ax.set_xlabel("Species' true breadth (Handbook habitats)"); ax.set_ylabel(f"{FEATURED_LABEL} vs Handbook")
ax.set_title("Fig 9. Where the LLM slope comes from\nBoth rise with breadth; precision is the weak point on specialists")
ax.set_ylim(-0.05,1.05); ax.grid(alpha=0.25); ax.legend(fontsize=9,loc="lower right")
fig.tight_layout(); fig.savefig(f"{OUT}/fig9_precision_recall_vs_breadth.png",dpi=140); plt.close(fig)
# Fig 10
fig,ax=plt.subplots(figsize=(6.5,6))
_rj=np.random.RandomState(0)
def j2(n): return (_rj.rand(n)-0.5)*0.22   # independent draw each call, so x and y jitter differ
ax.scatter(bd.book_breadth+j2(len(bd)),bd.llm_breadth+j2(len(bd)),s=48,alpha=0.5,color="#2b6cb0",label=FEATURED_LABEL)
ax.scatter(ed.book_breadth+j2(len(ed)),ed.expert_breadth+j2(len(ed)),s=48,alpha=0.5,color="#c05621",marker="^",label="Expert")
ax.plot([0,9],[0,9],color="grey",ls=":",label="y = x")
ax.set_xlim(0,7.5); ax.set_ylim(0,7.5)
ax.set_xlabel("True breadth (Handbook habitats)"); ax.set_ylabel("Asserted breadth")
ax.set_title("Fig 10. Does the source widen its answer for broad species?")
ax.grid(alpha=0.25); ax.legend(fontsize=9,loc="upper left")
fig.tight_layout(); fig.savefig(f"{OUT}/fig10_calibration_breadth.png",dpi=140); plt.close(fig)

# ---------- featured model key numbers ----------
fr=cfg[cfg.config_id==FEATURED].iloc[0]
fexp=lve[lve.config_id==FEATURED]
fexp_f1=float(fexp.f1_vs_expert.iloc[0]) if len(fexp) else float("nan")
print("FEATURED", FEATURED_LABEL,
      "| F1 vs Book",round(fr.f1_vs_book,3),"| F1 vs Data",round(fr.f1_vs_data,3),
      "| kappa",round(fr.kappa_vs_book,3),"| acc",round(fr.accuracy_vs_book,3),
      "| $/sp",round(fr.median_cost_per_species,4),"| lat",round(fr.median_latency_s,2),
      "| F1 vs expert",round(fexp_f1,3))
print("Pairwise Jaccard:\n",t4.to_string(index=False))
print("Ceiling means:\n",t5.to_string(index=False))
print("r(breadth,expert-F1) =",round(r_p,3))
print("expert consensus mean breadth =",round(bd.expert_breadth.mean(),2),
      "| Fig 8 Spearman r =",round(rho8,3),"p =",round(p8,3))
print("Wrote everything to:",OUT)
