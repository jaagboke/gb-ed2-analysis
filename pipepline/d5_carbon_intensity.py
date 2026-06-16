"""
D5 – Carbon Intensity
=====================
Pulls current regional carbon intensity from the NESO Carbon Intensity API,
maps the 14 granular regions to DNO licence areas, min-max normalises to 0–1,
and writes data/zones_d5_carbon.csv.

Source    : NESO Carbon Intensity API  (api.carbonintensity.org.uk)
Endpoint  : GET /regional  →  current 30-min snapshot for 18 GB regions
Regions   : IDs 1–14 correspond 1-to-1 with the 14 DNO licence areas.
            IDs 15–18 are aggregate zones (England / Scotland / Wales / GB)
            and are excluded.
Direction : Higher intensity → higher D5 score (greater marginal abatement
            value from renewable investment — see methodology_spec.docx §4).
Normalise : min-max across the 14 DNO zones  D_norm = (x − x_min)/(x_max − x_min)

Output columns
--------------
dno                  DNO licence area name
region_id            NESO region ID (1–14)
intensity_gco2_kwh   Raw forecast intensity (gCO₂eq/kWh) from the API
d5_score             Normalised score 0–1
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import requests

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

API_URL = "https://api.carbonintensity.org.uk/regional"

# NESO region IDs 1–14 map directly to the 14 GB DNO licence areas.
# Source: api.carbonintensity.org.uk/regional  (regionid field)
REGION_TO_DNO: dict[int, str] = {
    1:  "SSEN (Scottish Hydro)",
    2:  "SP Distribution",
    3:  "Electricity North West",
    4:  "Northern Powergrid (Northeast)",
    5:  "Northern Powergrid (Yorkshire)",
    6:  "SP Manweb",
    7:  "NGED South Wales",
    8:  "NGED West Midlands",
    9:  "NGED East Midlands",
    10: "UKPN East of England",
    11: "NGED South West",
    12: "SSEN (Southern Electric)",
    13: "UKPN London",
    14: "UKPN South East",
}

# Resolved relative to this file so the script can be run from any directory.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PATH = PROJECT_ROOT / "data" / "zones_d5_carbon.csv"


# ---------------------------------------------------------------------------
# Pipeline steps
# ---------------------------------------------------------------------------

def fetch_regional_intensity() -> list[dict]:
    """Return the list of region objects from the NESO /regional endpoint."""
    resp = requests.get(API_URL, headers={"Accept": "application/json"}, timeout=10)
    resp.raise_for_status()
    return resp.json()["data"][0]["regions"]


def build_dno_frame(regions: list[dict]) -> pd.DataFrame:
    """
    Filter to the 14 DNO regions (IDs 1–14) and extract intensity forecasts.
    Aggregate regions 15–18 (England, Scotland, Wales, GB) are skipped.
    """
    rows = []
    for r in regions:
        rid = int(r["regionid"])
        if rid not in REGION_TO_DNO:
            continue
        rows.append({
            "dno": REGION_TO_DNO[rid],
            "region_id": rid,
            "intensity_gco2_kwh": r["intensity"]["forecast"],
        })

    if len(rows) != 14:
        raise ValueError(
            f"Expected 14 DNO regions, got {len(rows)}. "
            "The NESO API region structure may have changed."
        )

    return pd.DataFrame(rows).sort_values("region_id").reset_index(drop=True)


def normalise(df: pd.DataFrame) -> pd.DataFrame:
    """
    Min-max normalise intensity_gco2_kwh → d5_score (0–1).
    Higher intensity = higher score (no inversion needed; see spec §4 D5 direction).
    Edge case: if all zones report identical intensity, scores default to 0.5.
    """
    x = df["intensity_gco2_kwh"]
    x_min, x_max = x.min(), x.max()

    if x_max == x_min:
        df = df.copy()
        df["d5_score"] = 0.5
    else:
        df = df.copy()
        df["d5_score"] = (x - x_min) / (x_max - x_min)

    df["d5_score"] = df["d5_score"].round(6)
    return df


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run() -> pd.DataFrame:
    """Fetch, transform, normalise, and persist D5 carbon intensity scores."""
    print("D5 | Fetching regional carbon intensity from NESO API …")
    regions = fetch_regional_intensity()

    df = build_dno_frame(regions)
    df = normalise(df)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUTPUT_PATH, index=False)

    print(f"D5 | Saved {len(df)} DNO zones -> {OUTPUT_PATH.relative_to(PROJECT_ROOT)}")
    return df


if __name__ == "__main__":
    result = run()
    print()
    print(result.to_string(index=False))
