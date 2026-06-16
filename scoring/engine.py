"""
Scoring Engine - WADD Composite Scoring
=========================================
Loads the five dimension CSVs, merges them on the canonical DNO name, and
computes Weighted Additive (WADD) composite scores for three predefined
weight scenarios plus optional custom weights from the command line.

WADD formula:  composite(z) = sum(w_i * D_i(z))  for dimensions i = 1..5

Weight scenarios
----------------
S1 Equal          : w = [0.20, 0.20, 0.20, 0.20, 0.20]
S2 Investor-Focus : w = [0.35, 0.25, 0.25, 0.05, 0.10]
S3 Just Transition: w = [0.15, 0.15, 0.20, 0.35, 0.15]

Dimension order: D1 Headroom, D2 Constraints, D3 Demand Growth,
                 D4 Vulnerability, D5 Carbon Intensity

D4 note: Three non-English DNOs (SSEN Scottish Hydro, SP Distribution, NGED
South Wales) have pending Scotland/Wales deprivation data. Their d4_score is
treated as 0.0 (minimum) when computing composites, which is conservative but
flags the data gap. A warning is printed for any such rows.

Input files (relative to project root data/)
--------------------------------------------
zones_d1_headroom.csv    - dno, region_id, ttc_lvssb_days, d1_score
zones_d2_constraints.csv - dno, region_id, binding_boundary, constraint_metric, d2_score
zones_d3_demand.csv      - dno, region_id, growth_metric, d3_score
zones_d4_vulnerability.csv - dno, region_id, lsoa_count, total_population, imd_score_wtd, d4_score, scotland_wales_note
zones_d5_carbon.csv      - dno, region_id, intensity_gco2_kwh, d5_score

Output
------
data/zones_ranked.csv
Columns: dno, region_id, d1_score, d2_score, d3_score, d4_score, d5_score,
         composite_s1, composite_s2, composite_s3,
         rank_s1, rank_s2, rank_s3
Rows are sorted by rank_s1 ascending (best zone first under equal weights).

CLI usage
---------
  python -m scoring.engine
      Run with predefined scenarios only.

  python -m scoring.engine --weights 0.4 0.2 0.2 0.1 0.1
      Run predefined scenarios AND a custom scenario. Weights must sum to 1.0
      (tolerance 0.001). Results are printed but not appended to the CSV.

  python -m scoring.engine --help
      Show this help.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR     = PROJECT_ROOT / "data"
OUTPUT_PATH  = DATA_DIR / "zones_ranked.csv"

DIMENSION_FILES = {
    "d1": DATA_DIR / "zones_d1_headroom.csv",
    "d2": DATA_DIR / "zones_d2_constraints.csv",
    "d3": DATA_DIR / "zones_d3_demand.csv",
    "d4": DATA_DIR / "zones_d4_vulnerability.csv",
    "d5": DATA_DIR / "zones_d5_carbon.csv",
}

SCORE_COLS = ["d1_score", "d2_score", "d3_score", "d4_score", "d5_score"]

# ---------------------------------------------------------------------------
# Weight scenarios
# ---------------------------------------------------------------------------

SCENARIOS: dict[str, list[float]] = {
    "s1": [0.20, 0.20, 0.20, 0.20, 0.20],   # Equal weights
    "s2": [0.35, 0.25, 0.25, 0.05, 0.10],   # Investor-focused
    "s3": [0.15, 0.15, 0.20, 0.35, 0.15],   # Just Transition
}

SCENARIO_LABELS = {
    "s1": "Equal (0.20 each)",
    "s2": "Investor-focused (D1 0.35 / D2 0.25 / D3 0.25 / D4 0.05 / D5 0.10)",
    "s3": "Just Transition (D1 0.15 / D2 0.15 / D3 0.20 / D4 0.35 / D5 0.15)",
}


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_dimensions() -> pd.DataFrame:
    """
    Load all five dimension CSVs and merge on 'dno'.
    Returns a single DataFrame with one row per DNO zone (14 rows).
    """
    frames: dict[str, pd.DataFrame] = {}
    for dim, path in DIMENSION_FILES.items():
        if not path.exists():
            raise FileNotFoundError(
                f"Missing dimension file: {path}\n"
                f"Run pipepline/{dim}_*.py first to generate it."
            )
        df = pd.read_csv(path)
        if "dno" not in df.columns:
            raise ValueError(f"{path.name} has no 'dno' column.")
        frames[dim] = df

    # Start with D1 (includes region_id)
    merged = frames["d1"][["dno", "region_id", "d1_score"]].copy()

    # D4 pending rows: Scotland/Wales DNOs have NaN d4_score by design.
    # Identify them before merging so we can fill and warn appropriately.
    d4_raw = frames["d4"]
    pending_mask = d4_raw["scotland_wales_note"].notna() & (
        d4_raw["scotland_wales_note"].str.strip() != ""
    )
    pending_dnos = set(d4_raw.loc[pending_mask, "dno"].tolist())

    for dim in ("d2", "d3", "d4", "d5"):
        score_col = f"{dim}_score"
        src = frames[dim][["dno", score_col]]
        merged = merged.merge(src, on="dno", how="left")

        # For D4, NaN is expected for the pending Scotland/Wales zones; fill with 0.
        if dim == "d4":
            if pending_dnos:
                print(
                    f"Engine | Warning: D4 score set to 0.0 (data pending) "
                    f"for: {sorted(pending_dnos)}\n"
                    f"         Composite scores for these zones are "
                    f"conservative estimates."
                )
            merged["d4_score"] = merged["d4_score"].fillna(0.0)
        else:
            absent = merged[merged[score_col].isna()]["dno"].tolist()
            if absent:
                raise ValueError(
                    f"DNO(s) in D1 but absent from {dim}: {absent}"
                )

    merged = merged.sort_values("region_id").reset_index(drop=True)
    return merged


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def compute_composite(
    df: pd.DataFrame,
    weights: list[float],
    label: str,
) -> pd.Series:
    """
    Compute WADD composite score for the given weight vector.
    Returns a Series of composite values aligned to df.index.
    """
    assert len(weights) == 5, "Exactly 5 weights required (D1..D5)."
    total = sum(weights)
    if abs(total - 1.0) > 0.001:
        raise ValueError(
            f"Weights for scenario '{label}' sum to {total:.4f}, not 1.0."
        )

    score = sum(
        w * df[col] for w, col in zip(weights, SCORE_COLS)
    )
    return score.round(6)


def rank_scores(series: pd.Series) -> pd.Series:
    """Rank descending (highest composite = rank 1). Ties share the lower rank."""
    return series.rank(ascending=False, method="min").astype(int)


def run_scenarios(df: pd.DataFrame) -> pd.DataFrame:
    """Add composite_s1/s2/s3 and rank_s1/s2/s3 columns to df."""
    result = df.copy()
    for scenario, weights in SCENARIOS.items():
        composite_col = f"composite_{scenario}"
        rank_col      = f"rank_{scenario}"
        result[composite_col] = compute_composite(result, weights, scenario)
        result[rank_col]      = rank_scores(result[composite_col])
    return result


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------

def _scenario_table(df: pd.DataFrame, scenario: str, label: str) -> str:
    """Return a printable ranked table for one scenario."""
    rank_col      = f"rank_{scenario}"
    composite_col = f"composite_{scenario}"
    rows = df.sort_values(rank_col)[
        [rank_col, "dno", composite_col] + SCORE_COLS
    ].copy()
    rows.columns = ["Rank", "DNO", "Composite"] + [
        "D1", "D2", "D3", "D4", "D5"
    ]
    lines = [
        f"\n{'='*72}",
        f"  {label}",
        f"{'='*72}",
        rows.to_string(index=False, float_format="{:.4f}".format),
    ]
    return "\n".join(lines)


def print_results(df: pd.DataFrame, custom: tuple[list[float], str] | None = None) -> None:
    for scenario, label in SCENARIO_LABELS.items():
        print(_scenario_table(df, scenario, f"{scenario.upper()} {label}"))

    if custom is not None:
        weights, name = custom
        composite = compute_composite(df, weights, name)
        tmp = df.copy()
        tmp["composite_custom"] = composite
        tmp["rank_custom"] = rank_scores(tmp["composite_custom"])
        label = f"Custom  {name}  weights={[round(w,4) for w in weights]}"
        rows = tmp.sort_values("rank_custom")[
            ["rank_custom", "dno", "composite_custom"] + SCORE_COLS
        ].copy()
        rows.columns = ["Rank", "DNO", "Composite", "D1", "D2", "D3", "D4", "D5"]
        print(f"\n{'='*72}")
        print(f"  CUSTOM  {label}")
        print(f"{'='*72}")
        print(rows.to_string(index=False, float_format="{:.4f}".format))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run(custom_weights: list[float] | None = None) -> pd.DataFrame:
    """
    Load data, compute scores for three scenarios, save output CSV.

    Parameters
    ----------
    custom_weights : list of 5 floats, optional
        Additional weight vector to evaluate (not written to CSV).

    Returns
    -------
    DataFrame with all composite scores and ranks.
    """
    print("Engine | Loading dimension scores ...")
    df = load_dimensions()
    print(f"Engine | Loaded {len(df)} DNO zones, {len(SCORE_COLS)} dimensions")

    df = run_scenarios(df)

    output_cols = (
        ["dno", "region_id"]
        + SCORE_COLS
        + ["composite_s1", "composite_s2", "composite_s3"]
        + ["rank_s1", "rank_s2", "rank_s3"]
    )
    df_out = df[output_cols]

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df_out.to_csv(OUTPUT_PATH, index=False)
    print(f"Engine | Saved -> {OUTPUT_PATH.relative_to(PROJECT_ROOT)}")

    custom_arg = None
    if custom_weights is not None:
        custom_arg = (custom_weights, "CLI")

    print_results(df, custom=custom_arg)
    return df_out


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "GB Green Investment Tool — scoring engine.\n"
            "Computes WADD composite scores for 14 DNO zones across three "
            "predefined weight scenarios (S1/S2/S3)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python -m scoring.engine\n"
            "  python -m scoring.engine --weights 0.4 0.2 0.2 0.1 0.1\n"
        ),
    )
    parser.add_argument(
        "--weights",
        nargs=5,
        type=float,
        metavar=("D1", "D2", "D3", "D4", "D5"),
        help=(
            "Five custom weights for D1..D5 (must sum to 1.0). "
            "Results are printed but not added to the output CSV."
        ),
    )
    args = parser.parse_args()

    custom_weights: list[float] | None = None
    if args.weights is not None:
        total = sum(args.weights)
        if abs(total - 1.0) > 0.001:
            parser.error(
                f"Custom weights sum to {total:.4f}. They must sum to 1.0."
            )
        custom_weights = args.weights

    run(custom_weights=custom_weights)


if __name__ == "__main__":
    main()
