"""Phase 6 follow-up - does MORE model power help?

Same county-grouped folds, same training rows and same scoring as model.py, but with bigger
forests, extra-trees, a much larger boosting search and a Poisson count model that uses
population as the exposure. If the extra compute buys nothing, the limit is the information in
the features, not the capacity of the model.
"""
import time

import duckdb
import numpy as np
import pandas as pd
from sklearn.ensemble import ExtraTreesRegressor, HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LinearRegression, PoissonRegressor
from sklearn.model_selection import GridSearchCV, GroupKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from model import DB, N_SPLITS, PREDICTORS, RANDOM_STATE, TABLE_DIR, TARGET, fit_with_tuning, load, score

TREE_GRID = {"model__min_samples_leaf": [2, 5, 10, 25],
             "model__max_features": [0.5, 1.0],
             "model__max_depth": [8, None]}


def heavy_models():
    def impute():
        return ("impute", SimpleImputer(strategy="median"))
    return {
        "linear_regression (reference)": (Pipeline([impute(), ("scale", StandardScaler()),
                                                    ("model", LinearRegression())]), None),
        "random_forest, 1000 trees": (Pipeline([impute(), ("model", RandomForestRegressor(
                                          n_estimators=1000, random_state=RANDOM_STATE))]), TREE_GRID),
        "extra_trees, 1000 trees": (Pipeline([impute(), ("model", ExtraTreesRegressor(
                                        n_estimators=1000, random_state=RANDOM_STATE))]), TREE_GRID),
        "gradient_boosting, 24-point grid": (Pipeline([impute(), ("model", HistGradientBoostingRegressor(
                                                 random_state=RANDOM_STATE))]),
                                             {"model__learning_rate": [0.02, 0.05, 0.1],
                                              "model__max_iter": [300, 800],
                                              "model__min_samples_leaf": [10, 30],
                                              "model__l2_regularization": [0.0, 1.0]}),
    }


def fit_poisson(df, train, groups):
    """Poisson GLM for outlet COUNTS with population as exposure. Modelling the rate
    (outlets / population) with population as the sample weight is equivalent to a Poisson
    regression with a log(population) offset."""
    X = df[PREDICTORS].iloc[train]
    rate = (df["outlets_off"] / df["population"]).iloc[train]
    pipe = Pipeline([("impute", SimpleImputer(strategy="median")), ("scale", StandardScaler()),
                     ("model", PoissonRegressor(max_iter=2000))])
    search = GridSearchCV(pipe, {"model__alpha": [1e-6, 1e-3, 1e-1]}, cv=GroupKFold(n_splits=3),
                          scoring="neg_mean_poisson_deviance", n_jobs=-1)
    search.fit(X, rate, groups=groups.iloc[train], model__sample_weight=df["population"].iloc[train])
    return search.best_estimator_


def main():
    con = duckdb.connect(DB, read_only=True)
    df = load(con)
    X, y_log, groups = df[PREDICTORS], np.log1p(df[TARGET]), df["county"]
    flagged = df["visitor_heavy"].to_numpy()
    folds = GroupKFold(n_splits=N_SPLITS, shuffle=True, random_state=RANDOM_STATE)

    rows = []
    for fold, (train, test) in enumerate(folds.split(X, y_log, groups), start=1):
        train = train[~flagged[train]]
        normal = ~flagged[test]
        y_true = df[TARGET].iloc[test][normal]
        for name, (pipe, grid) in heavy_models().items():
            start = time.time()
            model = fit_with_tuning(pipe, grid, X.iloc[train], y_log.iloc[train], groups.iloc[train])
            pred_log = model.predict(X.iloc[test])
            rows.append(dict(fold=fold, model=name, seconds=time.time() - start,
                             **score(y_true, pred_log[normal])))
        start = time.time()
        poisson = fit_poisson(df, train, groups)
        pred_per_1k = poisson.predict(X.iloc[test]) * 1000
        rows.append(dict(fold=fold, model="poisson_count_model (offset = population)",
                         seconds=time.time() - start, **score(y_true, np.log1p(pred_per_1k[normal]))))
        print(f"fold {fold} done", flush=True)

    by_fold = pd.DataFrame(rows)
    agg = by_fold.groupby("model", sort=False)[["mae", "rmse", "r2", "seconds"]].agg(["mean", "std"])
    agg.columns = [f"{m}_{'mean' if s == 'mean' else 'sd'}" for m, s in agg.columns]
    agg = agg.reset_index()
    agg.round(4).to_csv(TABLE_DIR / "model_heavy_results.csv", index=False)
    print("\n", agg.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
