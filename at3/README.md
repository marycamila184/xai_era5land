# AT3 — Local explanations for heavy rain in Curitiba

Coursework for the XAI class (Atividade 03). Same table as [AT2](../at2/README.md), one ERA5-Land cell over Curitiba and one row per UTC day, now aimed at **heavy-rain days** and explained with local methods. This folder holds the regression part (Ceteris Paribus, ICE, LIME and SHAP; a DiCE counterfactual test stays in the notebook, out of the report). The classification part is built separately, on the same table and the same four days, from [`export/`](#handing-over-the-classification).

## The setup

**Heavy-rain day.** Precipitation ≥ 10 mm, the ETCCDI `R10mm` index. That is 2,395 days (14.3% of the record, about 52 a year) carrying 65% of all the rain. They are called *heavy*, not *extreme*, because the extreme for Curitiba is the 99th percentile of wet days, 48.6 mm/24 h (Goudard & Mendonça, 2020).

**The regression.** How much it rains, given that the day is heavy, so it is trained on heavy days only. A single decision tree, interpretable by construction:

| | Regression |
|---|---|
| Rows | heavy days only (1,857 in training) |
| Model | tree, Poisson, depth 4, min 50 per leaf, 11 leaves |
| CV (1995–2014) | RMSE 11.49 mm |
| Test (2015–2025) | RMSE 10.42 mm |
| Monthly climatology, test | RMSE 10.29 mm |

The tree ties with the monthly climatology, and in CV it is not distinguishable from a one-leaf tree. Its explanations describe how the tree decides, not what physically sets the amount of rain.

**Validation.** 1980–2014 is development, 2015–2025 is the test, touched once at the end. Inside development, five expanding-window folds validate on consecutive four-year blocks (1995–1998 … 2011–2014). Folds are cut on the **calendar**, not on rows: on the heavy-day subset, `TimeSeriesSplit(test_size=365*4)` would mean 27 years. The tree is the best of 192 (two criteria, depths 3–8, leaves 20–200 and two pruning schemes, over four feature sets). The final tree uses the twelve inputs below; the other sets, smaller or with other variables, did not improve the CV.

**Inputs.** Nine AT2 columns from t−1 (`ssrd_wm2`, `t2m`, `d2m`, `dpd`, `wind_speed`, `wind_const`, `wind_dir_sin`, `wind_dir_cos`, `tp_lag1`) plus the day of year (`day_sin`, `day_cos`, from day t, known in advance) and `wind850_speed_mean`, the scalar mean wind speed at 850 hPa from ERA5 at t−1. See the [AT2 README](../at2/README.md#columns) and [`commons/synoptic.py`](../commons/synoptic.py). Adding the daily maximum of the 850 hPa wind or its t−2 value did not improve the CV: the maximum is a near copy of the mean (Spearman 0.95) and the best tree never uses the t−2 value.

## Layout

```
at3/
├── analysis/
│   ├── atv3_extremos.ipynb         threshold, folds, baselines, regression tree
│   ├── atv3_explicabilidade.ipynb  CP, ICE, LIME, SHAP and DiCE on the regression tree
│   ├── modelos/                    the saved tree (.joblib, not versioned)
│   └── figuras*/                   figures of each notebook
├── relatorio/                      the report, LaTeX on the SBC template (not versioned, edited on Overleaf)
├── exportar_para_classificacao.py  writes the table and a LEIA-ME for the classification part
└── evaluation.py                   date folds and a smoothed climatology
```

The data and the scripts that build it are shared with AT2 and live in [`commons/`](../commons/).

## Run

```bash
uv sync --group dev
uv run python -m commons.build_curitiba_daily   # commons/data/curitiba_daily.parquet
uv run python -m commons.synoptic               # 850 hPa wind, CAPE, TCWV (ERA5)
uv run python -m commons.subdaily               # sub-daily columns
```

Then the notebooks, in order, from `at3/analysis/`: `atv3_extremos` saves the tree to `modelos/`, and `atv3_explicabilidade` explains it. The tree diagram in `atv3_extremos` needs the Graphviz `dot` binary (`sudo apt install graphviz`); without it that one cell fails and everything else runs. DiCE uses `dice-ml`.

Everything is seeded. Re-running reproduces the saved tree and the explanation figures.

## Handing over the classification

`uv run python -m at3.exportar_para_classificacao` writes two files to `at3/export/` (not versioned):

- `curitiba_at3.parquet`: every day with the 12 features, the rain, the heavy-day flag (`forte`, the classification target) and the train/test split;
- `LEIA-ME.md`: how the regression was built (split, calendar folds, grid, climatology baseline), so the classifier can follow the same process, plus the four days and some suggestions.

## The four observations

Four heavy days of the test, each picked by a rule that uses the regression only:

| Role | Date | Observed | Regression | Rule |
|---|---|---|---|---|
| largest event | 2024-11-07 | 79.9 mm | 17.6 mm | highest observed rain |
| right | 2021-10-16 | 20.6 mm | 20.6 mm | smallest regression error |
| overestimated | 2021-06-28 | 13.0 mm | 35.1 mm | largest regression overestimate |
| typical | 2019-04-07 | 16.0 mm | 17.6 mm | most common leaf, rain closest to the heavy-day median |

All four are heavy days, so the classifier can explain the same ones; a false positive of the classifier would be a non-heavy day and has no regression counterpart.

## Methods and settings

- **Ceteris Paribus** with `dalex`, one variable at a time over a grid of 101 quantiles of the heavy test days.
- **ICE / PDP** with `sklearn.inspection.partial_dependence(kind="both")` on the same grid; the plot draws 300 random curves.
- **LIME** (`lime` 0.2.0.1, `LimeTabularExplainer`), sampling from the **training** data: quartile discretisation, 5,000 samples, all 12 features, kernel width 0.75·√12 ≈ 2.6, ridge surrogate. Stability is checked over 10 seeds.
- **SHAP** with `TreeExplainer`, exact for the tree, in mm. The notebook asserts that base value + contributions equals the prediction for every explained day.
- **DiCE** (`dice-ml`, random search), tested in the notebook but left out of the report: counterfactuals that move the tree's forecast to 30–40 mm (or to 10–18 mm for the overestimated day), date held fixed, each one re-checked against the model and flagged when physically impossible.

### Caveats worth knowing

A CP or ICE curve moves one column and holds the rest, so it visits combinations that never happen: a dewpoint above the temperature, a `(sin, cos)` pair off the unit circle, June days with almost twice the strongest radiation ever recorded in June. LIME and DiCE sample each feature independently and have the same issue. SHAP is exact for the tree but splits credit between correlated inputs in a way that is debatable (Aas et al., 2021).

## References

- Muñoz-Sabater et al. (2021), ERA5-Land, *ESSD* 13, [doi:10.5194/essd-13-4349-2021](https://doi.org/10.5194/essd-13-4349-2021)
- Hersbach et al. (2020), ERA5, *QJRMS* 146, [doi:10.1002/qj.3803](https://doi.org/10.1002/qj.3803)
- ETCCDI, [index definitions](https://etccdi.pacificclimate.org/docs/ETCCDMIndicesComparison1.pdf); Zhang et al. (2011), *WIREs Clim. Change* 2, [doi:10.1002/wcc.147](https://doi.org/10.1002/wcc.147)
- Goudard & Mendonça (2020), *IdeAs* 15, [doi:10.4000/ideas.8082](https://doi.org/10.4000/ideas.8082)
- Bergmeir & Benítez (2012), cross-validation for time series, *Inf. Sci.* 191, [doi:10.1016/j.ins.2011.12.028](https://doi.org/10.1016/j.ins.2011.12.028)
- Biecek & Burzykowski (2021), *Explanatory Model Analysis*, CRC, [doi:10.1201/9781003025902](https://doi.org/10.1201/9781003025902)
- Goldstein et al. (2015), ICE, *JCGS* 24, [doi:10.1080/10618600.2014.907095](https://doi.org/10.1080/10618600.2014.907095)
- Ribeiro et al. (2016), LIME, KDD, [doi:10.1145/2939672.2939778](https://doi.org/10.1145/2939672.2939778)
- Mothilal et al. (2020), DiCE, FAT*, [doi:10.1145/3351095.3372850](https://doi.org/10.1145/3351095.3372850)
- Lundberg & Lee (2017), SHAP, NeurIPS; Lundberg et al. (2020), TreeSHAP, *Nat. Mach. Intell.* 2, [doi:10.1038/s42256-019-0138-9](https://doi.org/10.1038/s42256-019-0138-9)
- Aas et al. (2021), dependent features, *Artif. Intell.* 298, [doi:10.1016/j.artint.2021.103502](https://doi.org/10.1016/j.artint.2021.103502)
- Rudin (2019), *Nat. Mach. Intell.* 1, [doi:10.1038/s42256-019-0048-x](https://doi.org/10.1038/s42256-019-0048-x)
