"""Phase 5 - K-means market archetypes for California ZIP codes.

Run once with CHOSEN_K = None to scan k = 2..10, read outputs/tables/cluster_selection.csv and
outputs/figures/05_k_selection.png, then set CHOSEN_K and run again for the final clusters.
"""
from itertools import combinations
from math import ceil
from pathlib import Path

import duckdb
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.metrics import adjusted_rand_score, silhouette_score
from sklearn.preprocessing import StandardScaler

DB = "data/market_map.duckdb"
TABLE_DIR = Path("outputs/tables")
FIG_DIR = Path("outputs/figures")

RANDOM_STATE = 42
K_RANGE = range(2, 11)
CHOSEN_K = 5             # chosen from cluster_selection.csv: stable through k=6, elbow flattens near 5

# 5.1 - clustering features, and why each is in
FEATURES = {
    "log1p_off_per_1k": "store (off-sale) density; log scale tames the long right tail",
    "log1p_on_per_1k":  "bar/restaurant (on-sale) density; same transform",
    "on_share":         "retail mix: on-sale outlets as a share of all outlets",
    "log_income":       "affluence; log scale because income is right-skewed",
    "median_age":       "age profile of residents",
    "log_pop_density":  "urban vs rural character; log scale",
}
FEATURE_COLS = list(FEATURES)

# Chart tokens (light mode) from the dataviz reference palette; cluster number -> fixed hue.
SURFACE, INK, INK2, MUTED, GRID, BASE = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]

# Draft archetype names, keyed by cluster number (1 = lowest median income ... k = highest).
# They describe CHOSEN_K = 5; if you change k, rewrite them from outputs/tables/cluster_profile.csv.
CLUSTER_NAMES = {
    1: "Lower-income, low-density, store-heavy",
    2: "Sparse, older towns rich in bars and restaurants",
    3: "Dense, middle-income, few outlets per resident",
    4: "Higher-income, dense, bar-and-restaurant scene",
    5: "Affluent suburbs, few outlets of either kind",
}

# The two PCA axes in plain words: (topic, what the low end means, what the high end means).
# Read off outputs/tables/pca_loadings.csv; oriented_pca() fixes the signs so these stay true.
AXIS_WORDS = {
    0: ("income and retail mix", "lower income,\nstore-heavy", "higher income,\nbar/restaurant-heavy"),
    1: ("outlets per resident, age, density", "dense, younger,\nfew outlets", "sparse, older,\nmany outlets"),
}


def load(con):
    """ZIPs with a status: clustered, visitor_heavy (kept out of the fit), or missing_features."""
    extra = ["zip5", "city", "county", "population", "off_per_1k", "on_per_1k",
             "median_income", "pop_density", "visitor_heavy"]
    df = con.sql(f"SELECT {', '.join(extra + FEATURE_COLS)} FROM zip_features").df()
    df["status"] = "clustered"
    df.loc[df[FEATURE_COLS].isna().any(axis=1), "status"] = "missing_features"
    df.loc[df["visitor_heavy"] & (df["status"] == "clustered"), "status"] = "visitor_heavy"
    return df


def scan(X):
    """5.3 + 5.4 - inertia, silhouette and two kinds of stability for every k."""
    rows = []
    for k in K_RANGE:
        ref = KMeans(k, n_init=20, random_state=RANDOM_STATE).fit(X)
        silhouette = silhouette_score(X, ref.labels_)

        # Stability 1: same data, 10 different random starts -> do they agree?
        runs = [KMeans(k, n_init=10, random_state=seed).fit(X).labels_ for seed in range(10)]
        ari_seeds = np.mean([adjusted_rand_score(a, b) for a, b in combinations(runs, 2)])

        # Stability 2: fit on random 80% subsamples, label ALL ZIPs, compare with the full fit.
        rng = np.random.default_rng(RANDOM_STATE)
        boot = []
        for _ in range(20):
            idx = rng.choice(len(X), size=int(0.8 * len(X)), replace=False)
            model = KMeans(k, n_init=10, random_state=RANDOM_STATE).fit(X[idx])
            boot.append(adjusted_rand_score(ref.labels_, model.predict(X)))

        rows.append(dict(k=k, inertia=ref.inertia_, silhouette=silhouette,
                         ari_seeds=ari_seeds, ari_subsample=np.mean(boot)))
    return pd.DataFrame(rows)


def oriented_pca(X):
    """2-D PCA with its arbitrary signs fixed: PC1 rises with income, PC2 with on-sale density."""
    pca = PCA(n_components=2, random_state=RANDOM_STATE).fit(X)
    coords = pca.transform(X)
    for i, feature in enumerate(["log_income", "log1p_on_per_1k"]):
        if pca.components_[i, FEATURE_COLS.index(feature)] < 0:
            coords[:, i] *= -1
            pca.components_[i] *= -1
    return coords, pca


# ---------------------------------------------------------------- charts
def style_axes(ax):
    ax.set_facecolor(SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(BASE)
        ax.spines[side].set_linewidth(0.7)
    ax.tick_params(color=BASE, labelcolor=MUTED, labelsize=9, length=3, width=0.7)
    ax.grid(True, color=GRID, linewidth=0.6, linestyle="-")
    ax.set_axisbelow(True)


def setup_fonts():
    plt.rcParams["font.family"] = "sans-serif"
    plt.rcParams["font.sans-serif"] = ["Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans"]


def plot_selection(sel, path, chosen_k):
    """Three small charts (never two y-scales on one chart): elbow, silhouette, stability."""
    setup_fonts()
    fig, axes = plt.subplots(1, 3, figsize=(12, 3.8), facecolor=SURFACE)
    line = dict(lw=1.0, marker="o", markersize=5, markeredgecolor=SURFACE, markeredgewidth=1.0)

    ax = axes[0]
    ax.plot(sel["k"], sel["inertia"], color=SERIES[0], **line)
    ax.set_title("Inertia (look for the elbow)", loc="left", color=INK, fontsize=11)
    ax.set_ylabel("Within-cluster sum of squares", color=INK2, fontsize=9)

    ax = axes[1]
    ax.plot(sel["k"], sel["silhouette"], color=SERIES[0], **line)
    ax.set_title("Silhouette (higher = better separated)", loc="left", color=INK, fontsize=11)
    ax.set_ylabel("Mean silhouette score", color=INK2, fontsize=9)

    ax = axes[2]
    ax.plot(sel["k"], sel["ari_seeds"], color=SERIES[0], label="Different random starts", **line)
    ax.plot(sel["k"], sel["ari_subsample"], color=SERIES[1], label="80% subsamples", **line)
    ax.set_title("Stability (1 = identical groupings)", loc="left", color=INK, fontsize=11)
    ax.set_ylabel("Adjusted Rand index", color=INK2, fontsize=9)
    ax.set_ylim(0, 1.02)
    leg = ax.legend(loc="lower left", frameon=False, fontsize=9)
    for text in leg.get_texts():
        text.set_color(INK2)

    for ax in axes:
        style_axes(ax)
        ax.set_xlabel("k (number of clusters)", color=INK2, fontsize=9)
        ax.set_xticks(list(sel["k"]))
        if chosen_k is not None:
            ax.axvline(chosen_k, color=BASE, linewidth=0.9)
    if chosen_k is not None:
        axes[0].text(chosen_k + 0.1, axes[0].get_ylim()[1], f"chosen k = {chosen_k}",
                     color=INK2, fontsize=9, va="top")

    fig.tight_layout()
    fig.savefig(path, dpi=150, facecolor=SURFACE)
    plt.close(fig)


def label_axis(ax, which, share):
    """Name a PCA axis in words: the topic as the axis label, the two ends as small notes."""
    i = 0 if which == "x" else 1
    topic, low, high = AXIS_WORDS[i]
    title = f"PC{i + 1} ({share:.0%} of variance): {topic}"
    note = dict(transform=ax.transAxes, color=MUTED, fontsize=8.5, linespacing=1.15)
    # A drawn double arrow shows the direction (arrow glyphs are missing from many fonts).
    arrow = dict(xycoords="axes fraction", textcoords="axes fraction", annotation_clip=False,
                 arrowprops=dict(arrowstyle="<->", color=BASE, linewidth=0.8, shrinkA=0, shrinkB=0))
    if which == "x":
        ax.set_xlabel(title, color=INK2, fontsize=9, labelpad=40)
        ax.annotate("", xy=(1, -0.115), xytext=(0, -0.115), **arrow)
        ax.text(0, -0.14, low, ha="left", va="top", **note)
        ax.text(1, -0.14, high, ha="right", va="top", **note)
    else:
        ax.set_ylabel(title, color=INK2, fontsize=9, labelpad=48)
        ax.annotate("", xy=(-0.115, 1), xytext=(-0.115, 0), **arrow)
        ax.text(-0.14, 0, low, rotation=90, ha="right", va="bottom", **note)
        ax.text(-0.14, 1, high, rotation=90, ha="right", va="top", **note)


def plot_clusters(coords, labels, var_ratio, path):
    """5.7 - PCA scatter as small multiples: one panel per cluster, that cluster in colour."""
    setup_fonts()
    k = int(labels.max())
    ncols = 3
    nrows = ceil(k / ncols)
    fig, axes = plt.subplots(nrows, ncols, figsize=(4.6 * ncols, 4.0 * nrows + 0.9),
                             sharex=True, sharey=True, facecolor=SURFACE, squeeze=False)
    for c, ax in zip(range(1, k + 1), axes.flat):
        mask = labels == c
        ax.scatter(coords[~mask, 0], coords[~mask, 1], s=14, color=BASE, linewidths=0, zorder=2)
        ax.scatter(coords[mask, 0], coords[mask, 1], s=20, color=SERIES[c - 1],
                   edgecolors=SURFACE, linewidths=0.8, zorder=3)
        ax.set_title(f"Cluster {c}   ({mask.sum():,} ZIPs)", loc="left", color=INK, fontsize=11, pad=22)
        ax.text(0, 1.02, CLUSTER_NAMES.get(c, ""), transform=ax.transAxes, color=INK2,
                fontsize=9, va="bottom")
        style_axes(ax)
    for ax in list(axes.flat)[k:]:
        ax.set_visible(False)
    # A panel whose neighbour below is hidden is the last visible one in its column:
    # give it its own x-axis numbers and label.
    bottoms = list(axes[-1]) + [axes[r - 1, c] for r in range(1, nrows)
                                for c in range(ncols) if not axes[r, c].get_visible()]
    for ax in bottoms:
        if ax.get_visible():
            ax.tick_params(labelbottom=True)
            label_axis(ax, "x", var_ratio[0])
    for ax in axes[:, 0]:
        label_axis(ax, "y", var_ratio[1])

    fig.suptitle("California ZIP market archetypes, seen through the first two principal components",
                 x=0.01, ha="left", color=INK, fontsize=13)
    fig.text(0.01, 0.01,
             "Each dot is one ZIP. Position summarizes six standardized features; ZIPs flagged "
             "visitor-heavy or missing a feature are not shown.",
             color=MUTED, fontsize=9, ha="left", va="bottom")
    fig.tight_layout(rect=(0, 0.04, 1, 0.95))
    fig.savefig(path, dpi=150, facecolor=SURFACE)
    plt.close(fig)


# ---------------------------------------------------------------- main
def main():
    TABLE_DIR.mkdir(parents=True, exist_ok=True)
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(DB)

    df = load(con)
    print(df["status"].value_counts().to_string(), "\n")
    fit_df = df[df["status"] == "clustered"].reset_index(drop=True)

    # 5.2 - features are already log-transformed in zip_features; standardize to mean 0, sd 1
    scaler = StandardScaler().fit(fit_df[FEATURE_COLS])
    X = scaler.transform(fit_df[FEATURE_COLS])

    sel = scan(X)
    sel.round(4).to_csv(TABLE_DIR / "cluster_selection.csv", index=False)
    print(sel.round(3).to_string(index=False))
    plot_selection(sel, FIG_DIR / "05_k_selection.png", CHOSEN_K)
    if CHOSEN_K is None:
        print("\nRead the table and figure, then set CHOSEN_K in src/cluster.py and run again.")
        return

    # Final fit. Clusters are renumbered 1..k from lowest to highest median income so the
    # numbering (and each cluster's colour) is stable and meaningful.
    km = KMeans(CHOSEN_K, n_init=50, random_state=RANDOM_STATE).fit(X)
    order = pd.Series(fit_df["log_income"]).groupby(km.labels_).median().sort_values().index.to_numpy()
    remap = {old: new + 1 for new, old in enumerate(order)}
    labels = np.array([remap[v] for v in km.labels_])
    centers = km.cluster_centers_[order]

    # 5.6 - profile each cluster in ORIGINAL units (medians of ZIP values) + 5 typical ZIPs
    prof = fit_df.assign(cluster=labels).groupby("cluster").agg(
        n_zips=("zip5", "size"), population=("population", "sum"),
        off_per_1k=("off_per_1k", "median"), on_per_1k=("on_per_1k", "median"),
        on_share=("on_share", "median"), median_income=("median_income", "median"),
        median_age=("median_age", "median"), pop_density=("pop_density", "median"))
    dist = np.linalg.norm(X - centers[labels - 1], axis=1)
    examples = {}
    for c in range(1, CHOSEN_K + 1):
        idx = np.where(labels == c)[0]
        nearest = idx[np.argsort(dist[idx])[:5]]
        examples[c] = "; ".join(f"{fit_df.at[i, 'zip5']} {str(fit_df.at[i, 'city']).title()}" for i in nearest)
    prof["typical_zips"] = pd.Series(examples)
    prof["name"] = pd.Series(CLUSTER_NAMES)
    prof["population"] = prof["population"].astype(int)
    prof = prof.round(2)
    prof.to_csv(TABLE_DIR / "cluster_profile.csv")
    print("\n", prof.drop(columns=["typical_zips", "name"]).to_string())
    for c, text in examples.items():
        print(f"  cluster {c}: {text}")

    # 5.7 - zip_clusters table (every ZIP; visitor-heavy ZIPs get a nearest_cluster for context)
    out = df[["zip5", "city", "county", "status"]].copy()
    out["cluster"] = out["zip5"].map(dict(zip(fit_df["zip5"], labels))).astype("Int64")
    out["cluster_name"] = out["cluster"].map(lambda c: CLUSTER_NAMES.get(c) if pd.notna(c) else None)
    vh = df[(df["status"] == "visitor_heavy")]
    near = [remap[v] for v in km.predict(scaler.transform(vh[FEATURE_COLS]))]
    out["nearest_cluster"] = out["zip5"].map(dict(zip(vh["zip5"], near))).astype("Int64")
    con.register("zip_clusters_df", out)
    con.sql("CREATE OR REPLACE TABLE zip_clusters AS SELECT * FROM zip_clusters_df")
    out.to_csv(TABLE_DIR / "zip_clusters.csv", index=False)

    coords, pca = oriented_pca(X)
    loadings = pd.DataFrame(pca.components_.T, index=FEATURE_COLS, columns=["PC1", "PC2"]).round(2)
    loadings.to_csv(TABLE_DIR / "pca_loadings.csv", index_label="feature")
    print("\nPCA loadings:\n", loadings.to_string())
    plot_clusters(coords, labels, pca.explained_variance_ratio_, FIG_DIR / "05_pca_clusters.png")
    print("\nWrote zip_clusters table, cluster_profile.csv, and both figures.")


if __name__ == "__main__":
    main()
