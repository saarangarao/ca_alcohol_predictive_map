"""Phase 6 - predict off-sale outlet density from demographics, validated on held-out counties.

Every model is trained on log(1 + off_per_1k) and scored on the original scale (outlets per
1,000 residents). Folds hold out WHOLE COUNTIES, so each ZIP is predicted by a model that never
saw any ZIP from its county. Tuning happens only inside the training folds.
"""
from pathlib import Path

import duckdb
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.dummy import DummyRegressor
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import GridSearchCV, GroupKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from cluster import BASE, GRID, INK, INK2, MUTED, SERIES, SURFACE, setup_fonts, style_axes

DB = "data/market_map.duckdb"
TABLE_DIR = Path("outputs/tables")
FIG_DIR = Path("outputs/figures")

RANDOM_STATE = 42
N_SPLITS = 5

TARGET = "off_per_1k"
# 6.2 - demographics only. Nothing derived from the target (so no on_share), no race or ethnicity.
PREDICTORS = ["log_population", "log_income", "median_age", "log_pop_density"]
PLAIN = {"log_population": "Population (log)", "log_income": "Median income (log)",
         "median_age": "Median age", "log_pop_density": "Population density (log)"}


def load(con):
    cols = ["zip5", "city", "county", "visitor_heavy", "population", "outlets_off", TARGET] + PREDICTORS
    df = con.sql(f"SELECT {', '.join(cols)} FROM zip_features ORDER BY zip5").df()
    clusters = con.sql("SELECT zip5, cluster, cluster_name FROM zip_clusters").df()
    return df.merge(clusters, on="zip5", how="left")


def make_models():
    """4 models: 2 baselines and 2 flexible ones. Each is (pipeline, tuning grid or None).
    Missing income (28 ZIPs) is filled with the TRAINING-fold median, inside every pipeline."""
    def impute():
        return ("impute", SimpleImputer(strategy="median"))
    return {
        "baseline_mean": (Pipeline([impute(), ("model", DummyRegressor(strategy="mean"))]), None),
        "linear_regression": (Pipeline([impute(), ("scale", StandardScaler()),
                                        ("model", LinearRegression())]), None),
        "random_forest": (Pipeline([impute(), ("model", RandomForestRegressor(
                              n_estimators=300, random_state=RANDOM_STATE))]),
                          {"model__min_samples_leaf": [3, 10, 25], "model__max_depth": [6, None]}),
        "hist_gradient_boosting": (Pipeline([impute(), ("model", HistGradientBoostingRegressor(
                                       max_iter=200, random_state=RANDOM_STATE))]),
                                   {"model__learning_rate": [0.03, 0.1], "model__min_samples_leaf": [10, 30]}),
    }


def fit_with_tuning(pipe, grid, X, y, groups):
    """6.5 - light tuning, using only the training rows, with an inner county-grouped split."""
    if grid is None:
        return pipe.fit(X, y)
    search = GridSearchCV(pipe, grid, cv=GroupKFold(n_splits=3),
                          scoring="neg_root_mean_squared_error", n_jobs=-1)
    search.fit(X, y, groups=groups)
    return search.best_estimator_


def score(y_true, pred_log):
    """6.6 - metrics on the ORIGINAL scale (outlets per 1,000 residents)."""
    pred = np.clip(np.expm1(pred_log), 0, None)
    return dict(mae=mean_absolute_error(y_true, pred),
                rmse=float(np.sqrt(mean_squared_error(y_true, pred))),
                r2=r2_score(y_true, pred))


def run_cv(df, train_on_flagged):
    """6.3 - county-grouped K-fold. Returns per-fold scores, importances, out-of-fold predictions."""
    X, y_log, groups = df[PREDICTORS], np.log1p(df[TARGET]), df["county"]
    flagged = df["visitor_heavy"].to_numpy()
    folds = GroupKFold(n_splits=N_SPLITS, shuffle=True, random_state=RANDOM_STATE)

    oof = {name: np.full(len(df), np.nan) for name in make_models()}
    fold_of = np.zeros(len(df), dtype=int)
    rows, importances = [], []
    for fold, (train, test) in enumerate(folds.split(X, y_log, groups), start=1):
        fold_of[test] = fold
        if not train_on_flagged:
            train = train[~flagged[train]]
        for name, (pipe, grid) in make_models().items():
            model = fit_with_tuning(pipe, grid, X.iloc[train], y_log.iloc[train], groups.iloc[train])
            pred_log = model.predict(X.iloc[test])
            oof[name][test] = pred_log
            normal = ~flagged[test]
            for scope, mask in [("non_flagged_zips", normal), ("all_zips", np.ones(len(test), bool))]:
                rows.append(dict(fold=fold, model=name, scope=scope,
                                 **score(df[TARGET].iloc[test][mask], pred_log[mask])))
            if name == "random_forest":
                # 6.7 - permutation importance on HELD-OUT rows (normal ZIPs only)
                imp = permutation_importance(model, X.iloc[test][normal], y_log.iloc[test][normal],
                                             scoring="r2", n_repeats=20, random_state=RANDOM_STATE)
                importances.append(pd.Series(imp.importances_mean, index=PREDICTORS, name=fold))
    return pd.DataFrame(rows), pd.DataFrame(importances), oof, fold_of


def summarize(by_fold):
    agg = by_fold.groupby(["scope", "model"])[["mae", "rmse", "r2"]].agg(["mean", "std"])
    agg.columns = [f"{m}_{'mean' if s == 'mean' else 'sd'}" for m, s in agg.columns]
    order = list(make_models())
    return agg.reset_index().sort_values(["scope", "model"],
                                         key=lambda c: c.map({n: i for i, n in enumerate(order)}) if c.name == "model" else c)


def plot_importance(imp, path):
    """Single series -> one colour, no legend; thin 2px stems with >= 8px end dots."""
    setup_fonts()
    mean, sd = imp.mean().sort_values(), imp.std().reindex(imp.mean().sort_values().index)
    fig, ax = plt.subplots(figsize=(8, 3.6), facecolor=SURFACE)
    y = np.arange(len(mean))
    ax.hlines(y, 0, mean.values, color=SERIES[0], linewidth=1.0, zorder=3)
    ax.errorbar(mean.values, y, xerr=sd.values, fmt="none", ecolor=BASE, elinewidth=0.9,
                capsize=3, zorder=2)
    ax.scatter(mean.values, y, s=60, color=SERIES[0], edgecolors=SURFACE, linewidths=1.0, zorder=4)
    for yi, m in zip(y, mean.values):
        ax.text(m + 0.012 + float(sd.iloc[yi]), yi, f"{m:.2f}", va="center", color=INK2, fontsize=9)
    ax.set_yticks(y)
    ax.set_yticklabels([PLAIN[f] for f in mean.index], color=INK2, fontsize=10)
    ax.set_xlim(left=0)
    ax.set_xlabel("Drop in R² when the feature is shuffled (higher = more important)",
                  color=INK2, fontsize=9)
    ax.set_title("Which demographics matter most for off-sale outlet density?",
                 loc="left", color=INK, fontsize=12, pad=18)
    ax.text(0, 1.02, "Random forest, scored on held-out counties; dot = mean over 5 folds, whisker = ±1 sd",
            transform=ax.transAxes, color=MUTED, fontsize=9, va="bottom")
    style_axes(ax)
    ax.grid(axis="y", visible=False)
    fig.tight_layout()
    fig.savefig(path, dpi=150, facecolor=SURFACE)
    plt.close(fig)


def main():
    TABLE_DIR.mkdir(parents=True, exist_ok=True)
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(DB)
    df = load(con)
    print(f"{len(df):,} ZIPs, {df['visitor_heavy'].sum()} visitor-heavy, "
          f"{df['log_income'].isna().sum()} with missing income, {df['county'].nunique()} counties\n")

    results, by_fold_all = [], []
    for label, train_on_flagged in [("train_without_flagged", False), ("train_with_flagged", True)]:
        print(f"running: {label} ...")
        by_fold, imp, oof, fold_of = run_cv(df, train_on_flagged)
        by_fold.insert(0, "run", label)
        by_fold_all.append(by_fold)
        summary = summarize(by_fold)
        summary.insert(0, "run", label)
        results.append(summary)

        if label == "train_without_flagged":      # the main run
            imp.to_csv(TABLE_DIR / "permutation_importance_by_fold.csv", index_label="fold")
            plot_importance(imp, FIG_DIR / "06_permutation_importance.png")
            print("\npermutation importance (mean drop in R2):")
            print(imp.mean().sort_values(ascending=False).round(3).to_string())

            # 6.8 - out-of-fold predictions for EVERY ZIP, and the residual
            out = df[["zip5", "city", "county", "cluster", "cluster_name", "visitor_heavy",
                      "population", "outlets_off", TARGET]].copy()
            out["fold"] = fold_of
            for name, pred_log in oof.items():
                out[f"pred_{name}"] = np.clip(np.expm1(pred_log), 0, None)
            out["residual_rf"] = out[TARGET] - out["pred_random_forest"]
            out.to_csv(TABLE_DIR / "oof_predictions.csv", index=False)
            con.register("oof_df", out)
            con.sql("CREATE OR REPLACE TABLE zip_residuals AS SELECT * FROM oof_df")

    summary = pd.concat(results, ignore_index=True)
    summary.round(4).to_csv(TABLE_DIR / "model_results.csv", index=False)
    pd.concat(by_fold_all).round(4).to_csv(TABLE_DIR / "model_results_by_fold.csv", index=False)
    show = summary.copy()
    for c in show.columns[3:]:
        show[c] = show[c].round(3)
    print("\n", show.to_string(index=False))
    print("\nWrote model_results.csv, oof_predictions.csv, permutation importance table and figure.")


if __name__ == "__main__":
    main()
