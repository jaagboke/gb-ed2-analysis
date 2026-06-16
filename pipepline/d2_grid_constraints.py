"""
D2 - Grid Constraint Severity
==============================
Pulls 24-months-ahead transmission constraint limits from the NESO open data
portal, maps each of the 14 DNO licence areas to its most relevant (binding)
transmission boundary, and min-max normalises to a 0-1 D2 score.

Source    : NESO Open Data Portal - "24 Months Ahead Constraint Limits"
Endpoint  : CKAN datastore_search on resource 3c359e33-3dac-4bdd-87d1-efbf4cbc2f07
            (https://data.nationalgrideso.com)
Metric    : Mean minimum binding transmission boundary limit (MW) per DNO zone,
            averaged across all available forecast weeks.
            Each DNO is assigned to its tightest relevant transmission boundary;
            see DNO_BOUNDARY_MAP for the mapping rationale.

Direction : Lower constraint limit (MW) -> higher constraint severity -> higher D2 score.
            Inverted min-max:  D_norm = 1 - (x - x_min) / (x_max - x_min)
            Zones with the tightest transmission limits face the highest
            constraint severity and therefore the greatest need for grid
            investment, producing a higher D2 score (see methodology_spec.docx §4 D2,
            §6 inverted normalisation).

Data note : The 24-months-ahead dataset covers transmission boundaries, not
            distribution. It is the closest publicly available open data proxy
            for zone-level constraint severity. Individual DNO network
            performance data (RIIO-ED2) would provide distribution-level
            constraint detail but is not available via a machine-readable API.

Output columns
--------------
dno                  DNO licence area name
region_id            NESO carbon-intensity region ID (1-14), for join with D5
binding_boundary     Transmission boundary that drives the constraint metric
constraint_metric    Mean MW limit on the binding boundary (higher = less constrained)
d2_score             Normalised score 0-1
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import requests

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RESOURCE_ID = "3c359e33-3dac-4bdd-87d1-efbf4cbc2f07"
DATASTORE_URL = "https://api.neso.energy/api/3/action/datastore_search"

# All 12 named transmission boundaries in the dataset.
BOUNDARIES = [
    "DRESHEX1",   # Dersingham (East Anglia / East Midlands border)
    "ESTEX",      # Eastern export (East England / Yorkshire)
    "FLOWSTH",    # North-South England main corridor
    "GM+ SNOW5A", # Greater Manchester + Snowdonia (NW England / N Wales)
    "HARSPNBLY",  # Wales / West Midlands boundary
    "NKILGRMO",   # South Wales / Glamorgan
    "SCOTEX",     # Scotland export (Scotland -> England)
    "SEIMPPR2",   # South East import
    "SSE+GRM",    # Southern Scotland / Grimsby (NE England / Yorkshire)
    "SSEN-S",     # SSEN South (Hampshire / Isle of Wight)
    "SSE-SP2",    # South / South East
    "SSHARN3",    # Sharnbrook (East / West Midlands)
]

# Maps each DNO to the transmission boundaries that limit its export/import
# capacity. The binding constraint per DNO is the minimum across these.
# Mapping rationale: each boundary is assigned to DNOs whose territory it
# borders or whose generation export flows through it.
DNO_BOUNDARY_MAP: dict[str, list[str]] = {
    "SSEN (Scottish Hydro)":            ["SCOTEX"],
    "SP Distribution":                  ["SCOTEX"],
    "Electricity North West":           ["GM+ SNOW5A", "FLOWSTH"],
    "Northern Powergrid (Northeast)":   ["SSE+GRM", "FLOWSTH"],
    "Northern Powergrid (Yorkshire)":   ["SSE+GRM", "ESTEX"],
    "SP Manweb":                        ["GM+ SNOW5A", "HARSPNBLY"],
    "NGED South Wales":                 ["NKILGRMO", "HARSPNBLY"],
    "NGED West Midlands":               ["HARSPNBLY", "SSHARN3"],
    "NGED East Midlands":               ["SSHARN3", "DRESHEX1"],
    "UKPN East of England":             ["DRESHEX1", "ESTEX"],
    "NGED South West":                  ["NKILGRMO"],
    "SSEN (Southern Electric)":         ["SSEN-S"],
    "UKPN London":                      ["SSE-SP2", "SEIMPPR2"],
    "UKPN South East":                  ["SSE-SP2", "SEIMPPR2"],
}

# region_id matches the NESO Carbon Intensity API region IDs used in D5,
# enabling a left-join on (dno, region_id) in the scoring engine.
DNO_REGION_ID: dict[str, int] = {
    "SSEN (Scottish Hydro)":            1,
    "SP Distribution":                  2,
    "Electricity North West":           3,
    "Northern Powergrid (Northeast)":   4,
    "Northern Powergrid (Yorkshire)":   5,
    "SP Manweb":                        6,
    "NGED South Wales":                 7,
    "NGED West Midlands":               8,
    "NGED East Midlands":               9,
    "UKPN East of England":             10,
    "NGED South West":                  11,
    "SSEN (Southern Electric)":         12,
    "UKPN London":                      13,
    "UKPN South East":                  14,
}

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PATH = PROJECT_ROOT / "data" / "zones_d2_constraints.csv"


# ---------------------------------------------------------------------------
# Pipeline steps
# ---------------------------------------------------------------------------

def fetch_constraint_limits() -> pd.DataFrame:
    """
    Pull all rows from the 24-months-ahead constraint limits dataset.
    The datastore holds ~108 rows (weekly forecasts across 2 years).
    """
    params = {
        "resource_id": RESOURCE_ID,
        "limit": 500,  # well above the current row count
    }
    resp = requests.get(DATASTORE_URL, params=params, timeout=15)
    resp.raise_for_status()
    result = resp.json()["result"]

    df = pd.DataFrame(result["records"])
    for col in BOUNDARIES:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    print(f"D2 | Fetched {len(df)} forecast rows "
          f"(years {sorted(df['YEAR'].unique())})")
    return df


def compute_mean_limits(df: pd.DataFrame) -> dict[str, float]:
    """Return the mean MW limit per boundary across all forecast weeks."""
    return {b: float(df[b].mean()) for b in BOUNDARIES}


def build_dno_frame(mean_limits: dict[str, float]) -> pd.DataFrame:
    """
    For each DNO, find the binding (minimum) boundary and its mean limit.
    Lower limit = tighter constraint = lower D2 score.
    """
    rows = []
    for dno, boundaries in DNO_BOUNDARY_MAP.items():
        limits = {b: mean_limits[b] for b in boundaries}
        binding_boundary = min(limits, key=limits.__getitem__)
        constraint_metric = limits[binding_boundary]
        rows.append({
            "dno": dno,
            "region_id": DNO_REGION_ID[dno],
            "binding_boundary": binding_boundary,
            "constraint_metric": round(constraint_metric, 1),
        })

    return pd.DataFrame(rows).sort_values("region_id").reset_index(drop=True)


def normalise(df: pd.DataFrame) -> pd.DataFrame:
    """
    Inverted min-max normalise constraint_metric -> d2_score.
    Lower capacity limit = higher constraint severity = higher D2 score.
    Formula: D_norm = 1 - (x - x_min) / (x_max - x_min)
    """
    x = df["constraint_metric"]
    x_min, x_max = x.min(), x.max()

    df = df.copy()
    if x_max == x_min:
        df["d2_score"] = 0.5
    else:
        df["d2_score"] = (1 - (x - x_min) / (x_max - x_min)).round(6)

    return df


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run() -> pd.DataFrame:
    """Fetch, transform, normalise, and persist D2 constraint scores."""
    print("D2 | Fetching 24-month-ahead constraint limits from NESO portal ...")
    raw = fetch_constraint_limits()

    mean_limits = compute_mean_limits(raw)
    df = build_dno_frame(mean_limits)
    df = normalise(df)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUTPUT_PATH, index=False)
    print(f"D2 | Saved {len(df)} DNO zones -> {OUTPUT_PATH.relative_to(PROJECT_ROOT)}")
    return df


if __name__ == "__main__":
    result = run()
    print()
    print(result.to_string(index=False))
