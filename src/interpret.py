"""Phase 7 - interpretation and robustness.

7.1  most over- and under-predicted ZIPs, ranked two ways
7.2  residuals by archetype
7.3  robustness: population floor, flagged ZIPs removed, k +/- 1, other feature sets
Also: how much of the residual spread is small-count noise, and the Stockton check.
"""
import shutil
import tempfile
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import adjusted_rand_score, silhouette_score
from sklearn.model_selection import GroupKFold
from sklearn.preprocessing import StandardScaler

import build_features
import ingest_acs
from cluster import CLUSTER_NAMES, FEATURE_COLS
from cluster import load as load_cluster_frame
from model import DB, N_SPLITS, PREDICTORS, RANDOM_STATE, TABLE_DIR, TARGET, fit_with_tuning, make_models, score


# ------------------------------------------------------------------ residuals
def residual_frame(con):
    """Out-of-fold residuals plus a Poisson z-score: (actual - expected) / sqrt(expected), where
    expected = predicted rate x population. It asks 'how surprising is this COUNT?', so a ZIP with
    1,000 people and 5 outlets no longer outranks a big ZIP that is off by a lot more outlets."""
    r = con.sql("SELECT * FROM zip_residuals").df()
    r["expected"] = np.maximum(r["pred_random_forest"] * r["population"] / 1000, 0.1)
    r["z"] = (r["outlets_off"] - r["expected"]) / np.sqrt(r["expected"])
    return r


def top_lists(r, n=15):
    """7.1 - the n most over- and under-served normal ZIPs, by raw residual and by z."""
    d = r[~r["visitor_heavy"]]
    cols = ["zip5", "city", "county", "cluster", "population", "outlets_off",
            "expected", "residual_rf", "z"]
    parts = []
    for ranking, key in [("per_1k_residual", "residual_rf"), ("poisson_z", "z")]:
        for side, frame in [("over", d.nlargest(n, key)), ("under", d.nsmallest(n, key))]:
            part = frame[cols].copy()
            part.insert(0, "rank", range(1, len(part) + 1))
            part.insert(0, "side", side)
            part.insert(0, "ranking", ranking)
            parts.append(part)
    return pd.concat(parts, ignore_index=True)


def by_archetype(r):
    """7.2 - residuals by archetype. Caution: the archetypes were built partly FROM outlet
    densities (the thing being predicted), so this table is descriptive, not independent evidence."""
    d = r[~r["visitor_heavy"]].copy()
    d["archetype"] = d["cluster"].map(
        lambda c: f"{int(c)}: {CLUSTER_NAMES[int(c)]}" if pd.notna(c) else "not clustered (missing feature)")
    return d.groupby("archetype").agg(
        n_zips=("zip5", "size"), mean_residual=("residual_rf", "mean"),
        median_residual=("residual_rf", "median"), sd_residual=("residual_rf", "std"),
        pct_over_predicted=("residual_rf", lambda s: 100 * (s > 0).mean()), mean_z=("z", "mean")
    ).reset_index()


def spread_by_population(r):
    """If counts were pure Poisson noise, sd of z would be about 1. Well above 1 = real structure."""
    d = r[~r["visitor_heavy"]].copy()
    d["population_band"] = pd.cut(d["population"], [0, 3000, 10000, 30000, np.inf],
                                  labels=["under 3k", "3k-10k", "10k-30k", "over 30k"])
    return d.groupby("population_band", observed=True).agg(
        n_zips=("z", "size"), sd_residual_per_1k=("residual_rf", "std"), sd_z=("z", "std")).reset_index()


def city_table(r, min_zips=8):
    d = r[~r["visitor_heavy"] & r["city"].notna()]
    t = d.groupby("city").agg(n_zips=("zip5", "size"), population=("population", "sum"),
                              mean_residual=("residual_rf", "mean"), mean_z=("z", "mean"))
    return t[t["n_zips"] >= min_zips].sort_values("mean_residual").reset_index()


def stockton_check(r):
    """Is Stockton's mean residual unusual compared with random ZIPs from the same archetype?"""
    d = r[~r["visitor_heavy"]]
    st = d[d["city"] == "STOCKTON"]
    cluster = st["cluster"].mode()[0]
    pool = d[(d["cluster"] == cluster) & (d["city"] != "STOCKTON")]["residual_rf"].to_numpy()
    rng = np.random.default_rng(RANDOM_STATE)
    draws = np.array([rng.choice(pool, size=len(st), replace=False).mean() for _ in range(20000)])
    return pd.DataFrame([
        ("Stockton ZIPs", len(st)), ("archetype compared against", int(cluster)),
        ("Stockton mean residual (per 1k)", st["residual_rf"].mean()),
        ("same-archetype pool mean residual", pool.mean()),
        ("share of random same-size samples at or below Stockton", float(np.mean(draws <= st["residual_rf"].mean()))),
    ], columns=["metric", "value"])


# ------------------------------------------------------------------ robustness
def quintile_pattern(df, drop_flagged=False):
    """Pooled off-/on-sale outlets per 1,000 residents in the lowest and highest income quintile."""
    d = df[df["median_income"].notna()]
    if drop_flagged:
        d = d[~d["visitor_heavy"]]
    q = pd.qcut(d["median_income"].rank(method="first"), 5, labels=False)
    g = d.groupby(q).agg(pop=("population", "sum"), off=("outlets_off", "sum"), on=("outlets_on_core", "sum"))
    off, on = g["off"] / g["pop"] * 1000, g["on"] / g["pop"] * 1000
    ok = bool(off.iloc[-1] < off.iloc[0] and on.iloc[-1] > on.iloc[0])
    return ok, f"off per 1k Q1->Q5: {off.iloc[0]:.2f}->{off.iloc[-1]:.2f}; on per 1k: {on.iloc[0]:.2f}->{on.iloc[-1]:.2f}"


def quick_cv(df, predictors, models=("linear_regression", "random_forest")):
    """Mean R2 over county-grouped folds, same recipe as model.py (train without flagged ZIPs)."""
    X, y_log, groups = df[predictors], np.log1p(df[TARGET]), df["county"]
    flagged = df["visitor_heavy"].to_numpy()
    folds = GroupKFold(n_splits=N_SPLITS, shuffle=True, random_state=RANDOM_STATE)
    r2 = {m: [] for m in models}
    for train, test in folds.split(X, y_log, groups):
        train, normal = train[~flagged[train]], ~flagged[test]
        for m in models:
            pipe, grid = make_models()[m]
            model = fit_with_tuning(pipe, grid, X.iloc[train], y_log.iloc[train], groups.iloc[train])
            pred = model.predict(X.iloc[test])
            r2[m].append(score(df[TARGET].iloc[test][normal], pred[normal])["r2"])
    return {m: float(np.mean(v)) for m, v in r2.items()}


def model_verdict(r2):
    lin, rf = r2["linear_regression"], r2["random_forest"]
    ok = bool(0.20 <= lin <= 0.40 and rf - lin < 0.03)
    return ok, f"linear R2 {lin:.3f}, forest R2 {rf:.3f}"


def floor_variant(floor, workdir):
    """Rebuild zip_base and zip_features with a different population floor, in a throwaway copy."""
    tmp = Path(workdir) / f"floor_{floor}.duckdb"
    shutil.copy(DB, tmp)
    con = duckdb.connect(str(tmp))
    original = ingest_acs.POP_FLOOR
    try:
        ingest_acs.POP_FLOOR = floor
        ingest_acs.build_acs_clean(con)
        ingest_acs.build_zip_base(con)
        build_features.build_zip_features(con)
        return con.sql("SELECT * FROM zip_features ORDER BY zip5").df()
    finally:
        ingest_acs.POP_FLOOR = original
        con.close()


def cluster_variants(con, resid):
    """k +/- 1 and other feature sets: do the clusters agree with the main ones, and is the
    highest-residual archetype still the sparse, older one?"""
    frame = load_cluster_frame(con)
    fit = frame[frame["status"] == "clustered"].reset_index(drop=True)
    main_labels = fit["zip5"].map(resid.set_index("zip5")["cluster"]).to_numpy()
    details = fit[["zip5", "population", "pop_density", "median_age"]].merge(
        resid[["zip5", "residual_rf"]], on="zip5")
    variants = [
        ("k = 4", FEATURE_COLS, 4), ("k = 6", FEATURE_COLS, 6),
        ("k = 5, without on_share", [f for f in FEATURE_COLS if f != "on_share"], 5),
        ("k = 5, outlet and density features only",
         ["log1p_off_per_1k", "log1p_on_per_1k", "on_share", "log_pop_density"], 5),
    ]
    rows = []
    for label, feats, k in variants:
        X = StandardScaler().fit_transform(fit[feats])
        labels = KMeans(k, n_init=50, random_state=RANDOM_STATE).fit_predict(X)
        top = details.assign(c=labels).groupby("c").agg(
            mean_resid=("residual_rf", "mean"), density=("pop_density", "median"),
            age=("median_age", "median"), n=("zip5", "size")).sort_values("mean_resid").iloc[-1]
        ok = bool(top["density"] < 150 and top["age"] > 45)
        rows.append(dict(
            finding="F4: sparse, older towns are the most over-served archetype", check="clusters",
            variant=label,
            result=(f"agreement with main clusters (ARI) {adjusted_rand_score(main_labels, labels):.2f}; "
                    f"silhouette {silhouette_score(X, labels):.2f}; top-residual cluster: "
                    f"{int(top['n'])} ZIPs, median density {top['density']:.0f}/sq mi, median age {top['age']:.0f}"),
            survives=ok))
    return rows


def robustness(con_main, resid):
    df_main = con_main.sql("SELECT * FROM zip_features ORDER BY zip5").df()
    rows = []
    f1 = "F1: higher-income ZIPs have fewer stores and more bars/restaurants per resident"
    f2 = "F2: demographics explain about 30% of held-out variation; the forest does not beat linear"
    f3 = "F3: density and income carry the predictive signal"

    ok, text = quintile_pattern(df_main)
    rows.append(dict(finding=f1, check="baseline", variant="floor 1,000 (main)", result=text, survives=ok))
    ok, text = quintile_pattern(df_main, drop_flagged=True)
    rows.append(dict(finding=f1, check="flagged ZIPs removed", variant="floor 1,000", result=text, survives=ok))
    ok, text = model_verdict(quick_cv(df_main, PREDICTORS))
    rows.append(dict(finding=f2, check="baseline", variant="floor 1,000 (main)", result=text, survives=ok))
    main_lin = quick_cv(df_main, PREDICTORS, ("linear_regression",))["linear_regression"]

    with tempfile.TemporaryDirectory() as workdir:
        for floor in (500, 2000):
            df = floor_variant(floor, workdir)
            ok, text = quintile_pattern(df)
            rows.append(dict(finding=f1, check="population floor", variant=f"floor {floor:,} ({len(df):,} ZIPs)",
                             result=text, survives=ok))
            ok, text = model_verdict(quick_cv(df, PREDICTORS))
            rows.append(dict(finding=f2, check="population floor", variant=f"floor {floor:,} ({len(df):,} ZIPs)",
                             result=text, survives=ok))

    for label, preds in [("density + income only", ["log_pop_density", "log_income"]),
                         ("without population", ["log_income", "median_age", "log_pop_density"]),
                         ("without age", ["log_population", "log_income", "log_pop_density"])]:
        lin = quick_cv(df_main, preds, ("linear_regression",))["linear_regression"]
        rows.append(dict(finding=f3, check="predictor set", variant=label,
                         result=f"linear R2 {lin:.3f} (all four: {main_lin:.3f})",
                         survives=bool(lin >= main_lin - 0.03)))

    rows += cluster_variants(con_main, resid)
    return pd.DataFrame(rows)


def main():
    TABLE_DIR.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(DB, read_only=True)
    resid = residual_frame(con)

    top_lists(resid).round(3).to_csv(TABLE_DIR / "07_top_residuals.csv", index=False)
    arch = by_archetype(resid)
    arch.round(3).to_csv(TABLE_DIR / "07_residuals_by_archetype.csv", index=False)
    spread = spread_by_population(resid)
    spread.round(3).to_csv(TABLE_DIR / "07_residual_spread_by_population.csv", index=False)
    city_table(resid).round(3).to_csv(TABLE_DIR / "07_city_residuals.csv", index=False)
    stockton = stockton_check(resid)
    stockton.round(3).to_csv(TABLE_DIR / "07_stockton_check.csv", index=False)
    print("residuals by archetype:\n", arch.round(3).to_string(index=False))
    print("\nspread by population band:\n", spread.round(2).to_string(index=False))
    print("\nStockton check:\n", stockton.round(3).to_string(index=False))

    print("\nrunning robustness checks (a few minutes) ...", flush=True)
    rob = robustness(con, resid)
    rob.to_csv(TABLE_DIR / "07_robustness.csv", index=False)
    pd.set_option("display.max_colwidth", 140, "display.width", 250)
    print(rob[["check", "variant", "result", "survives"]].to_string(index=False))
    print(f"\n{int(rob['survives'].sum())} of {len(rob)} checks pass.")


if __name__ == "__main__":
    main()
