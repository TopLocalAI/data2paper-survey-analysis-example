#!/usr/bin/env python3
"""
End-to-end reproducible survey data analysis pipeline:
1. Read raw questionnaire CSV (data/survey_synthetic.csv)
2. Clean invalid responses (short completion time, straight-lining, missing values)
3. Reverse-score negatively worded Likert items (x_rev = 6 - x_raw)
4. Compute Cronbach's alpha reliability (custom implementation from variance formula)
5. Compute construct descriptive statistics and Pearson correlation matrix (scipy.stats)
6. Estimate OLS multiple linear regression from scratch using NumPy least squares
7. Export APA-style Markdown tables (results/) and publication-style plots (figures/)
"""

from __future__ import annotations

from pathlib import Path
import numpy as np
import pandas as pd
from scipy import stats
import matplotlib

# Force non-interactive Agg backend for deterministic headless rendering
matplotlib.use("Agg")
import matplotlib.pyplot as plt


MIN_DURATION_SEC = 60

RAW_LIKERT_COLS = [
    "PU1", "PU2", "PU3", "PU4_R",
    "SE1", "SE2", "SE3", "SE4_R",
    "LE1", "LE2", "LE3", "LE4_R",
]

CONSTRUCT_SPEC = {
    "PU": {
        "label": "Perceived Usefulness (PU)",
        "raw_cols": ["PU1", "PU2", "PU3", "PU4_R"],
        "scored_cols": ["PU1", "PU2", "PU3", "PU4_rev"],
        "reverse_map": {"PU4_R": "PU4_rev"},
    },
    "SE": {
        "label": "Academic Self-Efficacy (SE)",
        "raw_cols": ["SE1", "SE2", "SE3", "SE4_R"],
        "scored_cols": ["SE1", "SE2", "SE3", "SE4_rev"],
        "reverse_map": {"SE4_R": "SE4_rev"},
    },
    "LE": {
        "label": "Learning Engagement (LE)",
        "raw_cols": ["LE1", "LE2", "LE3", "LE4_R"],
        "scored_cols": ["LE1", "LE2", "LE3", "LE4_rev"],
        "reverse_map": {"LE4_R": "LE4_rev"},
    },
}


# =============================================================================
# Statistical Formulas Implemented from Scratch
# =============================================================================

def cronbach_alpha(items: np.ndarray) -> float:
    """
    Compute Cronbach's alpha internal consistency coefficient from scratch.

    Formula:
        alpha = (k / (k - 1)) * (1 - sum(Var(X_i)) / Var(sum(X_i)))

    Parameters
    ----------
    items : np.ndarray of shape (n_samples, k_items)
        Matrix of item responses (after reverse-scoring negatively worded items).

    Returns
    -------
    float
        Cronbach's alpha coefficient.
    """
    x = np.asarray(items, dtype=float)
    n_samples, k_items = x.shape
    if k_items < 2 or n_samples < 2:
        raise ValueError("Cronbach's alpha requires at least 2 items and 2 observations.")

    # Sample variance (ddof=1) of each item and of the summed scale score
    item_variances = np.var(x, axis=0, ddof=1)
    total_scores = np.sum(x, axis=1)
    total_variance = np.var(total_scores, axis=0, ddof=1)

    if total_variance == 0.0:
        return 0.0

    alpha = (k_items / (k_items - 1.0)) * (1.0 - np.sum(item_variances) / total_variance)
    return float(alpha)


def item_total_diagnostics(items: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """
    Compute Corrected Item-Total Correlations (CITC) and 'Alpha if Item Deleted'
    for each item in a multi-item scale.
    """
    x = np.asarray(items, dtype=float)
    _, k_items = x.shape
    citc = np.zeros(k_items, dtype=float)
    alpha_deleted = np.zeros(k_items, dtype=float)

    for j in range(k_items):
        rest = np.delete(x, j, axis=1)
        rest_sum = np.sum(rest, axis=1)
        r_val, _ = stats.pearsonr(x[:, j], rest_sum)
        citc[j] = r_val
        alpha_deleted[j] = cronbach_alpha(rest)

    return citc, alpha_deleted


def ols_regression_numpy(X_predictors: np.ndarray, y: np.ndarray) -> dict[str, np.ndarray | float | int]:
    """
    Estimate Ordinary Least Squares (OLS) multiple linear regression using NumPy.

    Automatically prepends an intercept column of ones to X_predictors.
    Computes unstandardized coefficients (B), standard errors (SE), standardized
    coefficients (beta), t-statistics, two-tailed p-values, 95% confidence
    intervals, R^2, Adjusted R^2, and overall F-test.
    """
    X_pred = np.asarray(X_predictors, dtype=float)
    y_vec = np.asarray(y, dtype=float).reshape(-1)

    n_obs, n_pred = X_pred.shape
    df_resid = n_obs - n_pred - 1
    if df_resid <= 0:
        raise ValueError("Insufficient degrees of freedom for OLS regression.")

    # Design matrix with intercept column [1, X_1, ..., X_p]
    X_design = np.column_stack([np.ones(n_obs, dtype=float), X_pred])

    # Solve min ||X * b - y||_2 via SVD-based least squares
    b_hat, _, _, _ = np.linalg.lstsq(X_design, y_vec, rcond=None)

    # Fitted values, residuals, and sums of squares
    # Use einsum / elementwise sum to avoid spurious Apple Accelerate AMX matmul warnings on macOS arm64
    y_hat = np.einsum("ij,j->i", X_design, b_hat)
    residuals = y_vec - y_hat

    ss_res = float(np.sum(residuals ** 2))
    ss_tot = float(np.sum((y_vec - np.mean(y_vec)) ** 2))
    ss_reg = ss_tot - ss_res

    # Goodness-of-fit: R^2 and Adjusted R^2
    r_squared = 1.0 - (ss_res / ss_tot)
    adj_r_squared = 1.0 - (1.0 - r_squared) * ((n_obs - 1.0) / df_resid)

    # Residual variance and parameter covariance matrix: s^2 * (X'X)^(-1)
    sigma2_hat = ss_res / df_resid
    xtx = np.einsum("ni,nj->ij", X_design, X_design)
    xtx_inv = np.linalg.inv(xtx)
    cov_b = sigma2_hat * xtx_inv
    se_b = np.sqrt(np.diag(cov_b))

    # Student's t-statistics, two-tailed p-values, and 95% confidence intervals
    t_stats = b_hat / se_b
    p_values = 2.0 * stats.t.sf(np.abs(t_stats), df=df_resid)
    t_crit = float(stats.t.ppf(0.975, df=df_resid))
    ci_low = b_hat - t_crit * se_b
    ci_high = b_hat + t_crit * se_b

    # Standardized coefficients (Beta): B_j * SD(X_j) / SD(Y); NaN for intercept
    sd_x = np.std(X_pred, axis=0, ddof=1)
    sd_y = float(np.std(y_vec, ddof=1))
    beta_std = np.empty(n_pred + 1, dtype=float)
    beta_std[0] = np.nan
    beta_std[1:] = b_hat[1:] * (sd_x / sd_y)

    # Omnibus model F-statistic and p-value
    ms_reg = ss_reg / n_pred
    ms_res = ss_res / df_resid
    f_stat = ms_reg / ms_res
    f_p_value = float(stats.f.sf(f_stat, dfn=n_pred, dfd=df_resid))

    return {
        "n": n_obs,
        "p": n_pred,
        "df_resid": df_resid,
        "b": b_hat,
        "se": se_b,
        "beta": beta_std,
        "t": t_stats,
        "p_val": p_values,
        "ci_low": ci_low,
        "ci_high": ci_high,
        "r2": r_squared,
        "adj_r2": adj_r_squared,
        "f_stat": f_stat,
        "f_pval": f_p_value,
    }


def format_p(p_val: float) -> str:
    """Format p-value in APA-compatible style with leading zero."""
    if p_val < 0.001:
        return "< 0.001"
    return f"{p_val:.3f}"


def sig_stars(p_val: float) -> str:
    """Return conventional significance stars."""
    if p_val < 0.001:
        return "***"
    if p_val < 0.01:
        return "**"
    if p_val < 0.05:
        return "*"
    return ""


# =============================================================================
# Main Analysis Pipeline
# =============================================================================

def main() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    csv_path = repo_root / "data" / "survey_synthetic.csv"
    results_dir = repo_root / "results"
    figures_dir = repo_root / "figures"
    results_dir.mkdir(parents=True, exist_ok=True)
    figures_dir.mkdir(parents=True, exist_ok=True)

    # -------------------------------------------------------------------------
    # Step 1: Load Raw Questionnaire Data & Clean Invalid Responses
    # -------------------------------------------------------------------------
    df_raw = pd.read_csv(csv_path)
    n_raw = len(df_raw)

    # Rule 1: Exclude overly fast completion times (< 60 seconds)
    mask_short = df_raw["duration_sec"] < MIN_DURATION_SEC
    n_excluded_short = int(mask_short.sum())
    df_step1 = df_raw.loc[~mask_short].copy()

    # Rule 2: Exclude straight-lining (identical value across all 12 raw Likert items)
    # Computed on complete Likert rows; rows with missing Likert values are handled in Rule 3
    likert_complete = df_step1[RAW_LIKERT_COLS].notna().all(axis=1)
    likert_std = df_step1[RAW_LIKERT_COLS].std(axis=1, ddof=0)
    mask_straight = likert_complete & (likert_std == 0.0)
    n_excluded_straight = int(mask_straight.sum())
    df_step2 = df_step1.loc[~mask_straight].copy()

    # Rule 3: Listwise deletion of incomplete responses (missing demographic or Likert cells)
    required_cols = ["gender", "grade", "major_category", "duration_sec", *RAW_LIKERT_COLS]
    mask_missing = df_step2[required_cols].isna().any(axis=1)
    n_excluded_missing = int(mask_missing.sum())
    df_clean = df_step2.loc[~mask_missing].copy().reset_index(drop=True)

    # Cast Likert columns to integer/float after missing-value removal
    for col in RAW_LIKERT_COLS:
        df_clean[col] = df_clean[col].astype(float)

    n_valid = len(df_clean)
    n_excluded_total = n_raw - n_valid
    valid_rate_pct = (n_valid / n_raw) * 100.0

    print("=== Step 1: Data Cleaning Summary ===")
    print(f"Initial raw responses           : {n_raw}")
    print(f"Excluded (duration < {MIN_DURATION_SEC}s)       : {n_excluded_short}")
    print(f"Excluded (straight-lining)      : {n_excluded_straight}")
    print(f"Excluded (missing values)       : {n_excluded_missing}")
    print(f"Total excluded                  : {n_excluded_total}")
    print(f"Final valid sample (N)          : {n_valid} ({valid_rate_pct:.1f}%)")
    print()

    # -------------------------------------------------------------------------
    # Step 2: Reverse-Score Negatively Worded Likert Items (6 - raw_score)
    # -------------------------------------------------------------------------
    for spec in CONSTRUCT_SPEC.values():
        for raw_col, rev_col in spec["reverse_map"].items():
            df_clean[rev_col] = 6.0 - df_clean[raw_col]

    # -------------------------------------------------------------------------
    # Step 3: Scale Reliability Analysis (Cronbach's Alpha) & Composite Scores
    # -------------------------------------------------------------------------
    reliability_rows = []
    for code, spec in CONSTRUCT_SPEC.items():
        raw_mat = df_clean[spec["raw_cols"]].to_numpy(dtype=float)
        scored_mat = df_clean[spec["scored_cols"]].to_numpy(dtype=float)

        alpha_raw = cronbach_alpha(raw_mat)
        alpha_scored = cronbach_alpha(scored_mat)
        citc, alpha_del = item_total_diagnostics(scored_mat)

        # Construct composite score = mean of the 4 scored items
        df_clean[code] = np.mean(scored_mat, axis=1)

        reliability_rows.append({
            "code": code,
            "label": spec["label"],
            "k": len(spec["scored_cols"]),
            "reverse_item": next(iter(spec["reverse_map"].keys())),
            "alpha": alpha_scored,
            "alpha_before_rev": alpha_raw,
            "citc_min": float(np.min(citc)),
            "citc_max": float(np.max(citc)),
            "alpha_del_max": float(np.max(alpha_del)),
        })

    print("=== Step 3: Reliability (Cronbach's Alpha) ===")
    for r in reliability_rows:
        print(
            f"{r['label']:<30} | k={r['k']} | alpha={r['alpha']:.3f} "
            f"(before reverse={r['alpha_before_rev']:.3f}) | "
            f"CITC=[{r['citc_min']:.3f}, {r['citc_max']:.3f}]"
        )
    print()

    # -------------------------------------------------------------------------
    # Step 4: Construct Descriptive Statistics & Pearson Correlation Matrix
    # -------------------------------------------------------------------------
    construct_codes = ["PU", "SE", "LE"]
    desc_stats = {}
    for code in construct_codes:
        vals = df_clean[code].to_numpy(dtype=float)
        desc_stats[code] = {
            "mean": float(np.mean(vals)),
            "sd": float(np.std(vals, ddof=1)),
            "min": float(np.min(vals)),
            "max": float(np.max(vals)),
        }

    k_con = len(construct_codes)
    corr_r = np.eye(k_con, dtype=float)
    corr_p = np.zeros((k_con, k_con), dtype=float)
    for i in range(k_con):
        for j in range(i + 1, k_con):
            r_val, p_val = stats.pearsonr(
                df_clean[construct_codes[i]].to_numpy(dtype=float),
                df_clean[construct_codes[j]].to_numpy(dtype=float),
            )
            corr_r[i, j] = corr_r[j, i] = float(r_val)
            corr_p[i, j] = corr_p[j, i] = float(p_val)

    print("=== Step 4: Construct Descriptives & Correlations ===")
    for i, code in enumerate(construct_codes):
        d = desc_stats[code]
        cors = ", ".join(
            f"r({code},{construct_codes[j]})={corr_r[i, j]:.3f} (p {format_p(corr_p[i, j])})"
            for j in range(k_con) if j != i
        )
        print(f"{code}: M={d['mean']:.2f}, SD={d['sd']:.2f} | {cors}")
    print()

    # -------------------------------------------------------------------------
    # Step 5: Multiple Linear Regression (OLS via NumPy)
    #   DV: Learning Engagement (LE)
    #   Focal IVs: Perceived Usefulness (PU), Academic Self-Efficacy (SE)
    #   Controls: Gender (Female=1), Grade (1..5), Major dummies (ref: STEM)
    # -------------------------------------------------------------------------
    grade_order = {"Freshman": 1.0, "Sophomore": 2.0, "Junior": 3.0, "Senior": 4.0, "Graduate": 5.0}
    df_clean["female"] = (df_clean["gender"] == "Female").astype(float)
    df_clean["grade_num"] = df_clean["grade"].map(grade_order).astype(float)
    df_clean["major_hss"] = (df_clean["major_category"] == "Humanities & Social Sciences").astype(float)
    df_clean["major_bus"] = (df_clean["major_category"] == "Business & Economics").astype(float)

    predictor_defs = [
        ("PU", "Perceived Usefulness (PU)"),
        ("SE", "Academic Self-Efficacy (SE)"),
        ("female", "Gender (Female = 1)"),
        ("grade_num", "Grade Level (1–5)"),
        ("major_hss", "Major: Humanities & Social Sciences"),
        ("major_bus", "Major: Business & Economics"),
    ]
    X_cols = [c for c, _ in predictor_defs]
    X_mat = df_clean[X_cols].to_numpy(dtype=float)
    y_vec = df_clean["LE"].to_numpy(dtype=float)

    ols = ols_regression_numpy(X_mat, y_vec)

    print("=== Step 5: OLS Multiple Linear Regression (DV = Learning Engagement) ===")
    print(
        f"N = {ols['n']}, R^2 = {ols['r2']:.3f}, Adjusted R^2 = {ols['adj_r2']:.3f}, "
        f"F({ols['p']}, {ols['df_resid']}) = {ols['f_stat']:.2f}, p {format_p(ols['f_pval'])}"
    )
    term_labels = ["(Intercept)", *[lbl for _, lbl in predictor_defs]]
    for idx, label in enumerate(term_labels):
        beta_str = "—" if np.isnan(ols["beta"][idx]) else f"{ols['beta'][idx]:.3f}"
        print(
            f"  {label:<36} B={ols['b'][idx]:6.3f}, SE={ols['se'][idx]:.3f}, "
            f"beta={beta_str:>6}, t={ols['t'][idx]:6.2f}, p {format_p(ols['p_val'][idx])}"
        )
    print()

    # -------------------------------------------------------------------------
    # Step 6: Write APA-Style Markdown Result Tables to results/
    # -------------------------------------------------------------------------

    # --- Table 1: Data Cleaning & Demographic Characteristics ---
    def demo_rows(col: str, categories: list[str], group_label: str) -> list[str]:
        lines = []
        counts = df_clean[col].value_counts()
        for i, cat in enumerate(categories):
            n_c = int(counts.get(cat, 0))
            pct_c = (n_c / n_valid) * 100.0
            var_cell = f"**{group_label}**" if i == 0 else ""
            lines.append(f"| {var_cell} | {cat} | {n_c} | {pct_c:.1f}% |")
        return lines

    dur_mean = float(df_clean["duration_sec"].mean())
    dur_sd = float(df_clean["duration_sec"].std(ddof=1))

    t1_lines = [
        "**Table 1**",
        "",
        f"*Sample Screening Summary and Demographic Characteristics of Valid Respondents (N = {n_valid})*",
        "",
        "| Variable | Category / Metric | n | % |",
        "| :--- | :--- | ---: | ---: |",
        f"| **Sample Screening** | Initial synthetic responses collected | {n_raw} | 100.0% |",
        f"| | Excluded: Completion time < {MIN_DURATION_SEC} s | {n_excluded_short} | {(n_excluded_short / n_raw) * 100.0:.1f}% |",
        f"| | Excluded: Straight-lining across 12 items | {n_excluded_straight} | {(n_excluded_straight / n_raw) * 100.0:.1f}% |",
        f"| | Excluded: Incomplete responses (missing values) | {n_excluded_missing} | {(n_excluded_missing / n_raw) * 100.0:.1f}% |",
        f"| | Total excluded | {n_excluded_total} | {(n_excluded_total / n_raw) * 100.0:.1f}% |",
        f"| | **Final valid sample** | **{n_valid}** | **{valid_rate_pct:.1f}%** |",
        *demo_rows("gender", ["Female", "Male"], "Gender"),
        *demo_rows("grade", ["Freshman", "Sophomore", "Junior", "Senior", "Graduate"], "Grade Level"),
        *demo_rows("major_category", ["STEM", "Humanities & Social Sciences", "Business & Economics"], "Major Category"),
        "",
        f"*Note.* Data are synthetic (`data/survey_synthetic.csv`, random seed = 2026). Percentages for demographic subgroups are calculated out of the valid sample ($N = {n_valid}$). Mean completion time among valid respondents was $M = {dur_mean:.1f}$ s ($SD = {dur_sd:.1f}$ s).",
        "",
    ]
    (results_dir / "table1_sample_demographics.md").write_text("\n".join(t1_lines), encoding="utf-8")

    # --- Table 2: Scale Reliability (Cronbach's Alpha) ---
    t2_lines = [
        "**Table 2**",
        "",
        f"*Internal Consistency Reliability (Cronbach's α) and Item-Total Diagnostics (N = {n_valid})*",
        "",
        "| Construct | Items (*k*) | Reverse-Worded Item | Cronbach's α | Raw α (Unreversed) | CITC Range | Max α if Item Deleted |",
        "| :--- | :---: | :---: | ---: | ---: | :---: | ---: |",
    ]
    for r in reliability_rows:
        t2_lines.append(
            f"| {r['label']} | {r['k']} | `{r['reverse_item']}` | {r['alpha']:.3f} | "
            f"{r['alpha_before_rev']:.3f} | {r['citc_min']:.3f}–{r['citc_max']:.3f} | {r['alpha_del_max']:.3f} |"
        )
    t2_lines.extend([
        "",
        "*Note.* CITC = Corrected item-total correlation. Reverse-worded items were recoded via $x_{\\text{rev}} = 6 - x_{\\text{raw}}$ prior to computing Cronbach's $\\alpha$. Comparing `Cronbach's α` with `Raw α (Unreversed)` illustrates why failing to recode reverse items severely distorts internal consistency.",
        "",
    ])
    (results_dir / "table2_reliability.md").write_text("\n".join(t2_lines), encoding="utf-8")

    # --- Table 3: Descriptive Statistics & Inter-Construct Correlations ---
    alpha_lookup = {r["code"]: r["alpha"] for r in reliability_rows}
    t3_lines = [
        "**Table 3**",
        "",
        f"*Descriptive Statistics and Inter-Construct Pearson Correlations (N = {n_valid})*",
        "",
        "| Variable | *M* | *SD* | Min | Max | 1 | 2 | 3 |",
        "| :--- | ---: | ---: | ---: | ---: | :---: | :---: | :---: |",
    ]
    for i, code in enumerate(construct_codes):
        d = desc_stats[code]
        label = f"{i + 1}. {CONSTRUCT_SPEC[code]['label']}"
        row_cells = []
        for j in range(k_con):
            if j == i:
                row_cells.append(f"({alpha_lookup[code]:.3f})")
            elif j < i:
                stars = sig_stars(corr_p[i, j])
                row_cells.append(f"{corr_r[i, j]:.3f}{stars}")
            else:
                row_cells.append("—")
        t3_lines.append(
            f"| {label} | {d['mean']:.2f} | {d['sd']:.2f} | {d['min']:.2f} | {d['max']:.2f} | "
            f"{row_cells[0]} | {row_cells[1]} | {row_cells[2]} |"
        )

    # Exact p-values summary in Note
    pair_notes = []
    for i in range(k_con):
        for j in range(i + 1, k_con):
            pair_notes.append(
                f"$r(\\text{{{construct_codes[i]}}}, \\text{{{construct_codes[j]}}}) = {corr_r[i, j]:.3f}$ ($p {format_p(corr_p[i, j])}$)"
            )
    t3_lines.extend([
        "",
        f"*Note.* Values on the diagonal in parentheses represent Cronbach's $\\alpha$ reliability coefficients. Exact two-tailed Pearson correlation tests: {'; '.join(pair_notes)}.",
        "*p* < 0.05 (*), *p* < 0.01 (**), *p* < 0.001 (***).",
        "",
    ])
    (results_dir / "table3_descriptives_correlations.md").write_text("\n".join(t3_lines), encoding="utf-8")

    # --- Table 4: Multiple Linear Regression ---
    t4_lines = [
        "**Table 4**",
        "",
        f"*OLS Multiple Linear Regression Predicting Learning Engagement (N = {n_valid})*",
        "",
        "| Predictor | *B* | *SE* | *β* | *t* | *p* | 95% CI |",
        "| :--- | ---: | ---: | ---: | ---: | ---: | :---: |",
    ]
    for idx, label in enumerate(term_labels):
        beta_cell = "—" if np.isnan(ols["beta"][idx]) else f"{ols['beta'][idx]:.3f}"
        ci_cell = f"[{ols['ci_low'][idx]:.3f}, {ols['ci_high'][idx]:.3f}]"
        t4_lines.append(
            f"| {label} | {ols['b'][idx]:.3f} | {ols['se'][idx]:.3f} | {beta_cell} | "
            f"{ols['t'][idx]:.2f} | {format_p(ols['p_val'][idx])} | {ci_cell} |"
        )
    t4_lines.extend([
        "",
        f"*Note.* Dependent variable: Learning Engagement (LE). Model fit: $R^2 = {ols['r2']:.3f}$, Adjusted $R^2 = {ols['adj_r2']:.3f}$, $F({ols['p']}, {ols['df_resid']}) = {ols['f_stat']:.2f}$, $p {format_p(ols['f_pval'])}$. *B* = unstandardized regression coefficient; *SE* = standard error; *β* = standardized regression coefficient; CI = confidence interval. Reference groups for categorical controls: Male (for Gender) and STEM (for Major Category). Grade Level is coded 1 (Freshman) to 5 (Graduate).",
        "",
    ])
    (results_dir / "table4_regression.md").write_text("\n".join(t4_lines), encoding="utf-8")

    # -------------------------------------------------------------------------
    # Step 7: Generate Publication-Style Figures (English Labels Only)
    # -------------------------------------------------------------------------
    plt.rcParams.update({
        "font.family": "sans-serif",
        "font.size": 10,
        "axes.edgecolor": "#333333",
        "axes.linewidth": 0.8,
    })

    # --- Figure 1: Inter-Construct Correlation Heatmap ---
    fig1, ax1 = plt.subplots(figsize=(6.4, 5.2), dpi=200)
    short_labels = [
        "Perceived\nUsefulness (PU)",
        "Academic\nSelf-Efficacy (SE)",
        "Learning\nEngagement (LE)",
    ]
    im = ax1.imshow(corr_r, cmap="Blues", vmin=0.0, vmax=1.0)
    cbar = fig1.colorbar(im, ax=ax1, fraction=0.046, pad=0.04)
    cbar.set_label("Pearson Correlation (r)", fontsize=10)

    ax1.set_xticks(np.arange(k_con))
    ax1.set_yticks(np.arange(k_con))
    ax1.set_xticklabels(short_labels, fontsize=9.5)
    ax1.set_yticklabels(short_labels, fontsize=9.5)

    for i in range(k_con):
        for j in range(k_con):
            val = corr_r[i, j]
            text_color = "white" if val >= 0.62 else "#1a1a1a"
            if i == j:
                cell_text = f"1.000\n(α = {alpha_lookup[construct_codes[i]]:.3f})"
            else:
                cell_text = f"r = {val:.3f}{sig_stars(corr_p[i, j])}"
            ax1.text(
                j, i, cell_text,
                ha="center", va="center",
                color=text_color, fontsize=9.5, fontweight="bold" if i != j else "normal",
            )

    ax1.set_title(
        f"Inter-Construct Pearson Correlations & Reliability (N = {n_valid})",
        fontsize=11, fontweight="bold", pad=12,
    )
    fig1.text(
        0.5, 0.01,
        "Note: Diagonal cells show Cronbach's alpha in parentheses. *** p < 0.001 (two-tailed).",
        ha="center", fontsize=8.5, color="#444444",
    )
    fig1.tight_layout(rect=[0.0, 0.04, 1.0, 1.0])
    fig1.savefig(
        figures_dir / "fig1_correlation_heatmap.png",
        dpi=200,
        metadata={"Software": "matplotlib"},
    )
    plt.close(fig1)

    # --- Figure 2: OLS Regression Coefficients & 95% CIs ---
    fig2, ax2 = plt.subplots(figsize=(7.4, 4.6), dpi=200)
    # Plot predictors excluding the intercept, ordered top-to-bottom
    pred_names = [lbl for _, lbl in predictor_defs]
    b_vals = ols["b"][1:]
    ci_l = ols["ci_low"][1:]
    ci_h = ols["ci_high"][1:]
    p_vals_pred = ols["p_val"][1:]

    y_pos = np.arange(len(pred_names))[::-1]
    colors = ["#1f5aa6" if p < 0.05 else "#7f8c8d" for p in p_vals_pred]

    ax2.axvline(0.0, color="#888888", linestyle="--", linewidth=1.0, zorder=1)
    for y_i, b_i, l_i, h_i, p_i, col in zip(y_pos, b_vals, ci_l, ci_h, p_vals_pred, colors):
        ax2.plot([l_i, h_i], [y_i, y_i], color=col, linewidth=2.2, zorder=2)
        ax2.scatter([b_i], [y_i], color=col, s=52, zorder=3)
        stars = sig_stars(p_i)
        ax2.text(
            h_i + 0.018, y_i,
            f"B = {b_i:.3f}{stars}",
            va="center", ha="left", fontsize=9, color="#222222",
        )

    ax2.set_yticks(y_pos)
    ax2.set_yticklabels(pred_names, fontsize=9.5)
    x_min = min(-0.22, float(np.min(ci_l)) - 0.08)
    x_max = float(np.max(ci_h)) + 0.22
    ax2.set_xlim(x_min, x_max)
    ax2.set_xlabel("Unstandardized Regression Coefficient (B) with 95% CI", fontsize=10)
    ax2.set_title(
        "OLS Regression Predicting Learning Engagement (LE)",
        fontsize=11, fontweight="bold", pad=10,
    )
    ax2.spines["top"].set_visible(False)
    ax2.spines["right"].set_visible(False)

    fit_summary = (
        f"N = {ols['n']} | R² = {ols['r2']:.3f} | Adj. R² = {ols['adj_r2']:.3f} | "
        f"F({ols['p']}, {ols['df_resid']}) = {ols['f_stat']:.2f}, p {format_p(ols['f_pval'])}"
    )
    fig2.text(
        0.5, 0.01,
        f"{fit_summary}   (* p < 0.05, ** p < 0.01, *** p < 0.001)",
        ha="center", fontsize=8.5, color="#444444",
    )
    fig2.tight_layout(rect=[0.0, 0.05, 1.0, 1.0])
    fig2.savefig(
        figures_dir / "fig2_regression_coefficients.png",
        dpi=200,
        metadata={"Software": "matplotlib"},
    )
    plt.close(fig2)

    print("=== Step 6 & 7: Saved Tables and Figures ===")
    for p in sorted(results_dir.glob("*.md")):
        print(f"  Table  -> {p.relative_to(repo_root)}")
    for p in sorted(figures_dir.glob("*.png")):
        print(f"  Figure -> {p.relative_to(repo_root)}")


if __name__ == "__main__":
    main()
