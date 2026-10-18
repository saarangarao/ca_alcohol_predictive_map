# Findings

All numbers come from public data only: California ABC license records (downloaded 2026-10-12) and
Census ACS 2024 5-year estimates. The project measures where outlets are licensed, not what they sell.
Every claim below is stated with its caveat; the tables are in `outputs/tables/`.

## 1. Higher-income ZIPs have fewer stores and more bars and restaurants per resident

| Income quintile | Median income range | Off-sale outlets per 1,000 | On-sale outlets per 1,000 |
|---|---|---|---|
| 1 (lowest) | $23k to $68k | 0.85 | 0.94 |
| 3 | $86k to $105k | 0.67 | 1.11 |
| 5 (highest) | $133k to $250k | 0.52 | 1.37 |

Evidence: `05_income_quintile_summary.csv`. The direction holds with a population floor of 500 or 2,000,
and with the visitor-heavy ZIPs removed (`07_robustness.csv`).
Caveat: this is a pattern across ZIP codes, not a statement about individuals or demand. Store format
(one license per corner store or per supermarket), zoning and regulation all differ by neighborhood and are
not in the data.

## 2. Four demographic features explain about 28% of off-sale density in counties the model has never seen, and a random forest does not beat a straight line

Held-out-county R², mean of 5 folds, visitor-heavy ZIPs excluded:

| Model | R² | MAE (outlets per 1,000) |
|---|---|---|
| Training mean | -0.06 | 0.43 |
| Linear regression | 0.287 +/- 0.044 | 0.349 |
| Random forest | 0.283 +/- 0.064 | 0.346 |
| Gradient boosting | 0.259 +/- 0.071 | 0.353 |

Evidence: `model_results.csv`. Larger models (1,000 trees, bigger search) reach at best 0.306, a gain smaller than
the fold-to-fold spread (`model_heavy_results.csv`).
Caveat: about 70% of the variation is unexplained. Visitors, local regulation, store format and small-count
noise are not in the features. Results are a single 2026 snapshot.

## 3. Population density and median income carry most of the predictive signal

Permutation importance on held-out counties (drop in R²): density 0.23, income 0.20, age 0.07, population 0.06
(`06_permutation_importance.png`). A linear model with density and income only scores R² 0.264, against 0.287
with all four.
Caveat: importance measures what the model uses to predict, not what causes outlet density. Density and income
are both proxies for how urban a place is.

## 4. Five market archetypes; sparse, older towns have more outlets than their demographics predict

| # | Archetype (draft names) | ZIPs | Mean residual (per 1,000) |
|---|---|---|---|
| 1 | Lower-income, low-density, store-heavy | 215 | +0.16 |
| 2 | Sparse, older towns rich in bars and restaurants | 160 | +0.46 |
| 3 | Dense, middle-income, few outlets per resident | 370 | -0.07 |
| 4 | Higher-income, dense, bar-and-restaurant scene | 231 | +0.22 |
| 5 | Affluent suburbs, few outlets of either kind | 372 | -0.13 |

Evidence: `cluster_profile.csv`, `07_residuals_by_archetype.csv`, `05_pca_clusters.png`. The pattern that sparse,
older towns have the largest positive residuals survives k = 4 and 6 and three other feature choices.
Caveats: the groups are weakly separated (silhouette about 0.21, a continuum rather than islands), and which ZIPs
land in which group moves between settings (agreement with the main clusters 0.49 to 0.82). The archetypes are
built partly from outlet densities, so the residual-by-archetype table is descriptive, not independent evidence.

## 5. The biggest surprises are mostly visitors and tiny-count noise, not unmet demand

- Most over-predicted by raw residual: small wine-country, resort and travel-stop ZIPs (Yountville, Cabazon, Olympic
  Valley, Borrego Springs, Temecula) with only 3 to 15 off-sale outlets.
- Most under-predicted by raw residual: tiny ZIPs with zero outlets (11 of the 15 have none; 14 of 15 have under
  3,000 residents).
- Ranking by a Poisson z-score instead (how surprising is the outlet COUNT?) moves the list to larger ZIPs: San
  Francisco, Sonoma County and coastal towns above expectation; Clovis, Fontana, Moreno Valley, Lancaster and
  parts of South Los Angeles below it.
- The z-score spread shows why: it is about 1.2 for ZIPs under 3,000 residents (close to pure count noise) and about 2.0 for
  ZIPs over 30,000 (real structure beyond the model).

Evidence: `07_top_residuals.csv`, `07_residual_spread_by_population.csv`.
Caveat: residuals are leads to investigate, not recommendations to open or close outlets. Local regulation can
produce the same pattern as low demand. As one check, Stockton, whose ordinance sets distance buffers and a
concentration limit, has a mean residual of -0.04 per 1,000; 66% of random same-size samples from the same
archetype land at or below that, so there is no evidence of a Stockton effect (low statistical power, one city;
`07_stockton_check.csv`).

## Limitations

1. Licenses are not sales. The data show market structure (who is licensed where), not demand or revenue.
2. Regulation shapes counts. State quotas and local ordinances cap some license types; neither is modeled.
3. Outlets, not rows. One premises can hold several licenses; outlets are counted per (license number, channel), so a
   premises with both an off-sale and an on-sale license counts once in each channel.
4. Snapshot and survivorship. The file lists current active licenses only; closed outlets are absent and issue
   date is not opening date.
5. ZIP versus ZCTA. 95 ABC ZIPs (123 outlets) have no Census area and are excluded; they are logged in
   `join_misses_abc`.
6. Small populations. ZIPs under 1,000 residents are excluded (383 ZIPs, 1,030 outlets); residuals for ZIPs under
   3,000 are largely sampling noise.
7. Visitor-heavy places. 28 ZIPs are flagged and excluded from training: 26 by a documented statistical rule and 2
   (Napa city) added by hand after the first modeling run showed their residuals. Results are unchanged when the
   flagged ZIPs are included in training.
8. ACS values are estimates with margins of error; the margins are kept but not propagated into the models.
   Median income is missing for 28 ZIPs (filled with the training-fold median) and is top-coded at $250,000.
9. Leakage. Cross-validation holds out whole counties, but ZIPs just across a county line still resemble their
   neighbors; no spatial blocking is used.
10. City names are free text and are used only as labels, never as join keys.
11. Overclaiming. Archetype names are interpretations, and residuals are prompts to investigate.
