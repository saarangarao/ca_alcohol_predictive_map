"""Phase 8 - the remaining core figures: density distribution, predicted vs actual, residual map.

(The PCA clusters, k-selection and permutation-importance figures are made by cluster.py and model.py.)
Every figure has a table twin in outputs/tables/.
"""
from pathlib import Path

import duckdb
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.cm import ScalarMappable
from matplotlib.colors import LinearSegmentedColormap, Normalize
from matplotlib.patheffects import withStroke
from matplotlib.lines import Line2D

from cluster import BASE, INK, INK2, MUTED, SERIES, SURFACE, setup_fonts, style_axes

DB = "data/market_map.duckdb"
TABLE_DIR = Path("outputs/tables")
FIG_DIR = Path("outputs/figures")

# Diverging ramp for residuals: cool blue pole, warm red pole, neutral gray midpoint.
DIVERGING = LinearSegmentedColormap.from_list(
    "residual", ["#1c5cab", "#86b6ef", "#f0efec", "#f0a9a3", "#c23b3a"])


def title_block(ax, title, subtitle):
    ax.set_title(title, loc="left", color=INK, fontsize=12, pad=26)
    ax.text(0, 1.03, subtitle, transform=ax.transAxes, color=MUTED, fontsize=9, va="bottom")


def plot_density_distribution(feat, path):
    """Off-sale density is right-skewed with a spike at zero, which is why the models use a log scale."""
    setup_fonts()
    x = feat["off_per_1k"].to_numpy()
    n_zero = int((x == 0).sum())
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 4.4), facecolor=SURFACE)
    bar = dict(color=SERIES[0], edgecolor=SURFACE, linewidth=1.0, zorder=3)

    ax = axes[0]
    ax.hist(x, bins=np.arange(0, 11.75, 0.25), **bar)
    median = float(np.median(x))
    ax.axvline(median, color=INK2, linewidth=1.0, zorder=4)
    ax.text(median + 0.2, ax.get_ylim()[1] * 0.96, f"median {median:.2f}", color=INK2, fontsize=9, va="top")
    ax.set_xlabel("Off-sale outlets per 1,000 residents", color=INK2, fontsize=9)
    title_block(ax, "As measured", f"{len(x):,} ZIP codes; {n_zero} have no off-sale outlet at all")

    ax = axes[1]
    ax.hist(np.log1p(x), bins=40, **bar)
    ax.set_xlabel("ln(1 + off-sale outlets per 1,000 residents)", color=INK2, fontsize=9)
    title_block(ax, "On the log scale the models use", "Same ZIP codes; the long right tail is pulled in")

    for ax in axes:
        style_axes(ax)
        ax.set_ylabel("Number of ZIP codes", color=INK2, fontsize=9)
    fig.suptitle("Off-sale outlet density is strongly right-skewed", x=0.01, ha="left", color=INK, fontsize=13)
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    fig.savefig(path, dpi=150, facecolor=SURFACE)
    plt.close(fig)


def plot_predicted_vs_actual(res, r2_mean, r2_sd, path, limit=6.2):
    """Out-of-fold predictions against reality. Two series (typical, flagged), so a legend is shown."""
    setup_fonts()
    fig, ax = plt.subplots(figsize=(7.6, 7.2), facecolor=SURFACE)
    typical, flagged = res[~res["visitor_heavy"]], res[res["visitor_heavy"]]
    # Predictions span a narrow range, so give the x axis only the room it needs.
    x_limit = float(np.ceil(res["pred_random_forest"].max() * 5) / 5)
    ax.plot([0, x_limit], [0, x_limit], color=BASE, linewidth=1.0, zorder=1)
    ax.text(x_limit - 0.03, x_limit + 0.08, "actual = predicted", color=MUTED, fontsize=8.5,
            ha="right", va="bottom")

    dots = dict(s=26, edgecolors=SURFACE, linewidths=0.8)
    ax.scatter(typical["pred_random_forest"], typical["off_per_1k"], color=SERIES[0], zorder=3,
               label=f"Typical ZIPs ({len(typical):,})", **dots)
    ax.scatter(flagged["pred_random_forest"], flagged["off_per_1k"], color=SERIES[1], zorder=4,
               label=f"Visitor-heavy ZIPs ({len(flagged)})", **dots)

    # Calibration: average actual density within each decile of the prediction
    d = typical.assign(bin=pd.qcut(typical["pred_random_forest"], 10, duplicates="drop"))
    cal = d.groupby("bin", observed=True)[["pred_random_forest", "off_per_1k"]].mean()
    ax.plot(cal["pred_random_forest"], cal["off_per_1k"], color=INK, linewidth=1.0, marker="o",
            markersize=5, markeredgecolor=SURFACE, markeredgewidth=1.0, zorder=5)
    ax.annotate("average actual,\nby prediction decile",
                xy=(cal["pred_random_forest"].iloc[-1], cal["off_per_1k"].iloc[-1]),
                xytext=(x_limit - 0.05, 0.25), color=INK2, fontsize=8.5, ha="right", va="center",
                arrowprops=dict(arrowstyle="-", color=BASE, linewidth=0.9, shrinkA=2, shrinkB=4))

    off_chart = int((res["off_per_1k"] > limit).sum())
    ax.set_xlim(0, x_limit)
    ax.set_ylim(0, limit)
    ax.set_xlabel("Predicted off-sale outlets per 1,000 residents", color=INK2, fontsize=9)
    ax.set_ylabel("Actual off-sale outlets per 1,000 residents", color=INK2, fontsize=9)
    style_axes(ax)
    leg = ax.legend(loc="upper right", frameon=False, fontsize=9)
    for text in leg.get_texts():
        text.set_color(INK2)
    title_block(ax, "Predicted vs. actual off-sale density, counties held out",
                f"Random forest, out-of-fold: each ZIP predicted by a model that never saw its county. "
                f"R² {r2_mean:.2f} ± {r2_sd:.2f} across folds.")
    note = "Visitor-heavy ZIPs were predicted but never used for training."
    if off_chart:
        note = f"{off_chart} ZIPs with actual density above {limit:g} are off the chart (all visitor-heavy). " + note
    fig.text(0.01, 0.01, note, color=MUTED, fontsize=8.5, ha="left", va="bottom")
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(path, dpi=150, facecolor=SURFACE)
    plt.close(fig)


def plot_residual_map(df, path, clip=2.0):
    """Map of residuals at ZIP centroids. Diverging colour: red = more outlets than predicted."""
    setup_fonts()
    fig, ax = plt.subplots(figsize=(7.4, 9.0), facecolor=SURFACE)
    norm = Normalize(vmin=-clip, vmax=clip)
    d = df.reindex(df["residual_rf"].abs().sort_values().index)        # extremes drawn on top
    typical, flagged = d[~d["visitor_heavy"]], d[d["visitor_heavy"]]

    ax.scatter(d["lon"], d["lat"], s=34, color=BASE, linewidths=0, zorder=1)      # context underlay
    dots = dict(cmap=DIVERGING, norm=norm, edgecolors=SURFACE, linewidths=0.6)
    ax.scatter(typical["lon"], typical["lat"], c=typical["residual_rf"], s=22, zorder=3, **dots)
    ax.scatter(flagged["lon"], flagged["lat"], c=flagged["residual_rf"], s=48, marker="^", zorder=4, **dots)

    # A few big cities for orientation (reference points, not data).
    for name, lon, lat in [("San Francisco", -122.42, 37.77), ("Sacramento", -121.49, 38.58),
                           ("Fresno", -119.79, 36.74), ("Los Angeles", -118.24, 34.05),
                           ("San Diego", -117.16, 32.72)]:
        ax.annotate(name, xy=(lon, lat), xytext=(8, 8), textcoords="offset points", color=INK2, fontsize=8.5,
                    zorder=6, path_effects=[withStroke(linewidth=2.5, foreground=SURFACE)],
                    arrowprops=dict(arrowstyle="-", color=INK2, linewidth=0.7, shrinkA=0, shrinkB=0))

    ax.set_aspect(1 / np.cos(np.deg2rad(37.5)))
    ax.set_xlabel("Longitude (degrees)", color=INK2, fontsize=9)
    ax.set_ylabel("Latitude (degrees)", color=INK2, fontsize=9)
    style_axes(ax)
    title_block(ax, "Where off-sale outlet counts run above or below what demographics predict",
                "Out-of-fold random-forest residuals, one dot per ZIP centroid; triangles are visitor-heavy ZIPs")
    handles = [
    Line2D([], [], marker="o", color="w", linestyle="None",
           markerfacecolor=DIVERGING(0.0), markeredgecolor=SURFACE,
           markersize=8, label="ZIP centroid"),
    Line2D([], [], marker="^", color="w", linestyle="None",
           markerfacecolor=DIVERGING(1.0), markeredgecolor=SURFACE,
           markersize=9, label="Visitor-heavy ZIP"),
]
    ax.legend(handles=handles, loc="lower left", fontsize=8.5, framealpha=0.9)
    cbar = fig.colorbar(ScalarMappable(norm=norm, cmap=DIVERGING), ax=ax, orientation="horizontal",
                        fraction=0.035, pad=0.09, ticks=[-clip, -clip / 2, 0, clip / 2, clip])
    cbar.ax.set_xticklabels([f"≤ {-clip:g}", f"{-clip / 2:g}", "0", f"+{clip / 2:g}", f"≥ +{clip:g}"])
    cbar.ax.tick_params(colors=MUTED, labelsize=8.5, length=0)
    cbar.outline.set_visible(False)
    cbar.set_label("Actual minus predicted off-sale outlets per 1,000 residents  "
                   "(red: more outlets than expected, blue: fewer)", color=INK2, fontsize=9)
    fig.text(0.01, 0.01, "Residuals are leads to investigate, not recommendations. Local rules, visitors and "
             "small counts all move them.", color=MUTED, fontsize=8.5, ha="left", va="bottom")
    fig.tight_layout(rect=(0, 0.025, 1, 1))
    fig.savefig(path, dpi=150, facecolor=SURFACE)
    plt.close(fig)


def main():
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(DB, read_only=True)
    feat = con.sql("SELECT zip5, off_per_1k, lat, lon, visitor_heavy FROM zip_features").df()
    res = con.sql("SELECT * FROM zip_residuals").df()
    results = pd.read_csv(TABLE_DIR / "model_results.csv")
    row = results[(results["run"] == "train_without_flagged") & (results["scope"] == "non_flagged_zips")
                  & (results["model"] == "random_forest")].iloc[0]

    plot_density_distribution(feat, FIG_DIR / "08_density_distribution.png")
    plot_predicted_vs_actual(res, row["r2_mean"], row["r2_sd"], FIG_DIR / "08_predicted_vs_actual.png")
    plot_residual_map(res.merge(feat[["zip5", "lat", "lon"]], on="zip5"), FIG_DIR / "08_residual_map.png")
    print("Wrote 08_density_distribution.png, 08_predicted_vs_actual.png, 08_residual_map.png")


if __name__ == "__main__":
    main()
