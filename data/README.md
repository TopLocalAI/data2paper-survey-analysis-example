# Synthetic Survey Dataset (`data/survey_synthetic.csv`)

> **Synthetic Data Notice / 合成数据说明**  
> `data/survey_synthetic.csv` is **100% computer-generated synthetic data** created solely for demonstrating a reproducible questionnaire data analysis workflow. Every respondent ID is prefixed with `SYN_` (`SYN_001`–`SYN_300`). These records do **not** represent real human participants and must **not** be cited as empirical evidence.  
> 本目录下的 `data/survey_synthetic.csv` 为**完全由程序生成的合成数据**（样本编号均以 `SYN_` 开头：`SYN_001`–`SYN_300`），仅用于演示问卷数据清洗、信度检验、相关分析与多元回归的可复现流程，并非真实受访者数据。

---

## 1. How the Dataset Is Generated / 生成方法

Run `data/generate_synthetic_survey.py` from the repository root:

```bash
python3 data/generate_synthetic_survey.py
```

Key generation details:

- **Random Number Generator**: NumPy `np.random.default_rng(2026)` (fixed seed `2026` for deterministic cross-run reproducibility).
- **CSV Format**: Standard UTF-8 CSV (`300` data rows + `1` header row on line 1, **no** leading comment lines so `pandas.read_csv()` and spreadsheet software open it directly).
- **Latent Structural Model** (for clean responses):
  - Two correlated standardized latent predictors—**Perceived Usefulness** ($Z_{\text{PU}}$) and **Academic Self-Efficacy** ($Z_{\text{SE}}$)—with latent correlation $\rho = 0.44$.
  - Latent outcome **Learning Engagement** ($Z_{\text{LE}}$) generated as:
    $$Z_{\text{LE}} = 0.38\,Z_{\text{PU}} + 0.47\,Z_{\text{SE}} + 0.08\,\text{grade\_std} + 0.67\,\varepsilon_3$$
  - Each latent construct is mapped to `4` five-point Likert items (`1` to `5`) via linear factor loadings (`0.71`–`0.79`) plus Gaussian measurement error ($\sigma_e \approx 0.54\text{–}0.55$), rounded and clipped to `{1, 2, 3, 4, 5}`.
  - The 4th item of each construct (`PU4_R`, `SE4_R`, `LE4_R`) is stored in **raw reverse-worded form** ($x_{\text{raw}} = 6 - x_{\text{true}}$) so the analysis script can demonstrate reverse-item recoding.
- **Injected Data-Quality Anomalies** (`24` disjoint rows out of `300`, leaving `276` valid rows):
  1. **Short completion time (`10` rows)**: `duration_sec` drawn from `18`–`55` seconds (`< 60` s threshold) with noisy random item clicks.
  2. **Straight-lining (`8` rows)**: Normal completion duration (`>= 75` s), but identical integer responses across all `12` raw Likert columns (ignoring reverse-worded items).
  3. **Missing values (`6` rows)**: `1`–`2` empty cells (`""`) in demographic or Likert columns to demonstrate listwise missing-data screening.

---

## 2. Variable Codebook / 变量编码表

| Column | Type | Values / Scale | Description |
| :--- | :--- | :--- | :--- |
| `respondent_id` | String | `SYN_001`–`SYN_300` | Synthetic respondent identifier (`SYN_` prefix marks synthetic records) |
| `gender` | Categorical | `Female`, `Male` | Respondent gender (性别) |
| `grade` | Categorical | `Freshman`, `Sophomore`, `Junior`, `Senior`, `Graduate` | Academic year / grade level (年级：大一至研究生) |
| `major_category` | Categorical | `STEM`, `Humanities & Social Sciences`, `Business & Economics` | Broad academic discipline (专业类别：理工科、人文社科、经管类) |
| `duration_sec` | Integer | Seconds (e.g., `18`–`540`) | Total survey completion time in seconds (作答时长，单位：秒) |
| `PU1`–`PU3` | Integer | `1`–`5` Likert (`1` = Strongly Disagree, `5` = Strongly Agree) | Positively worded items for **Perceived Usefulness (PU / 感知有用性)** |
| `PU4_R` | Integer | `1`–`5` Likert (**Reverse-worded / 反向题**) | Negatively worded item for PU; recode via `6 - PU4_R` before analysis |
| `SE1`–`SE3` | Integer | `1`–`5` Likert (`1` = Strongly Disagree, `5` = Strongly Agree) | Positively worded items for **Academic Self-Efficacy (SE / 学术自我效能感)** |
| `SE4_R` | Integer | `1`–`5` Likert (**Reverse-worded / 反向题**) | Negatively worded item for SE; recode via `6 - SE4_R` before analysis |
| `LE1`–`LE3` | Integer | `1`–`5` Likert (`1` = Strongly Disagree, `5` = Strongly Agree) | Positively worded items for **Learning Engagement (LE / 学习投入)** |
| `LE4_R` | Integer | `1`–`5` Likert (**Reverse-worded / 反向题**) | Negatively worded item for LE; recode via `6 - LE4_R` before analysis |
