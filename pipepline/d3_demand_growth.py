"""
D3 - Demand Growth (EV Adoption)
=================================
Measures the growth rate of plug-in electric vehicle (EV) registrations per
DNO licence area as a proxy for future demand growth from electrification of
transport, mapped to 14 DNO zones using DfT vehicle licensing data.

Source
------
DfT VEH0142: Licensed plug-in vehicles at the end of the quarter by local
authority. Quarterly time series 2009 Q4 - 2025 Q4.

URL : https://assets.publishing.service.gov.uk/media/
      69ef35539ca985145673b9d9/veh0142.ods

Vehicle filter
--------------
BodyType = "Cars"
Fuel     = "BATTERY ELECTRIC" OR "PLUG-IN HYBRID ELECTRIC (PETROL/DIESEL)"
Keepership = "Total"

These two fuel types represent all plug-in vehicles. Both create grid demand;
BEVs typically generate more per-vehicle grid load than PHEVs but PHEVs add
meaningfully to off-peak demand too.

Growth metric
-------------
3-year relative growth in licensed plug-in cars:
    growth = (count_2024Q4 - count_2021Q4) / count_2021Q4

Aggregated at DNO level by summing raw counts across constituent LADs before
computing the ratio (avoids weighting artefacts from averaging growth rates).

Direction : Higher growth = higher EV demand pressure = higher D3 score
            Standard min-max: D_norm = (x - x_min) / (x_max - x_min)

Geographic crosswalk
--------------------
England (317 LADs, E06/E07/E08/E09): imported from d4_vulnerability.LAD_TO_DNO
Scotland (32 council areas, S12): hardcoded below, split between SSEN Scottish
  Hydro (region_id 1, north/northeast) and SP Distribution (region_id 2,
  central belt/south).
Wales (22 unitary authorities, W06): hardcoded below, split between SP Manweb
  (region_id 6, north/mid) and NGED South Wales (region_id 7, south).

Output columns
--------------
dno             DNO licence area name
region_id       NESO carbon-intensity region ID (1-14), for joins
growth_metric   (count_2024Q4 - count_2021Q4) / count_2021Q4  (raw ratio)
d3_score        Normalised score 0-1  (higher = faster growth)
"""

from __future__ import annotations

import io
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import pandas as pd
import requests

from pipepline.d4_vulnerability import LAD_TO_DNO as _ENG_LAD_TO_DNO

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VEH0142_URL = (
    "https://assets.publishing.service.gov.uk/media/"
    "69ef35539ca985145673b9d9/veh0142.ods"
)

SHEET_NAME = "VEH0142"

PLUG_IN_FUELS = {"BATTERY ELECTRIC", "PLUG-IN HYBRID ELECTRIC (PETROL/DIESEL)"}

Q4_2024 = "2024 Q4"
Q4_2021 = "2021 Q4"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PATH  = PROJECT_ROOT / "data" / "zones_d3_demand.csv"

# DNO names and canonical region_ids (NESO Carbon Intensity API convention)
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

# ---------------------------------------------------------------------------
# Scotland LAD -> DNO crosswalk  (S12 ONS council area codes)
# Source: SP Energy Networks / SSEN licence area boundary maps.
# SSEN Scottish Hydro (1): Highlands, islands, Grampian, Tayside, Stirling.
# SP Distribution  (2): Central Belt, Edinburgh, Glasgow, Borders, Ayrshire.
# ---------------------------------------------------------------------------

_SCO_LAD_TO_DNO: dict[str, str] = {
    # --- SSEN Scottish Hydro ---
    "S12000013": "SSEN (Scottish Hydro)",   # Na h-Eileanan Siar (Western Isles)
    "S12000017": "SSEN (Scottish Hydro)",   # Highland
    "S12000020": "SSEN (Scottish Hydro)",   # Moray
    "S12000023": "SSEN (Scottish Hydro)",   # Orkney Islands
    "S12000027": "SSEN (Scottish Hydro)",   # Shetland Islands
    "S12000030": "SSEN (Scottish Hydro)",   # Stirling
    "S12000033": "SSEN (Scottish Hydro)",   # Aberdeen City
    "S12000034": "SSEN (Scottish Hydro)",   # Aberdeenshire
    "S12000035": "SSEN (Scottish Hydro)",   # Argyll and Bute
    "S12000041": "SSEN (Scottish Hydro)",   # Angus
    "S12000042": "SSEN (Scottish Hydro)",   # Dundee City
    "S12000048": "SSEN (Scottish Hydro)",   # Perth and Kinross

    # --- SP Distribution ---
    "S12000005": "SP Distribution",         # Clackmannanshire
    "S12000006": "SP Distribution",         # Dumfries and Galloway
    "S12000008": "SP Distribution",         # East Ayrshire
    "S12000010": "SP Distribution",         # East Lothian
    "S12000011": "SP Distribution",         # East Renfrewshire
    "S12000014": "SP Distribution",         # Falkirk
    "S12000018": "SP Distribution",         # Inverclyde
    "S12000019": "SP Distribution",         # Midlothian
    "S12000021": "SP Distribution",         # North Ayrshire
    "S12000026": "SP Distribution",         # Scottish Borders
    "S12000028": "SP Distribution",         # South Ayrshire
    "S12000029": "SP Distribution",         # South Lanarkshire
    "S12000036": "SP Distribution",         # City of Edinburgh
    "S12000038": "SP Distribution",         # Renfrewshire
    "S12000039": "SP Distribution",         # West Dunbartonshire
    "S12000040": "SP Distribution",         # West Lothian
    "S12000045": "SP Distribution",         # East Dunbartonshire
    "S12000047": "SP Distribution",         # Fife
    "S12000049": "SP Distribution",         # Glasgow City
    "S12000050": "SP Distribution",         # North Lanarkshire
}

# ---------------------------------------------------------------------------
# Wales LAD -> DNO crosswalk  (W06 ONS unitary authority codes)
# SP Manweb (6): North and Mid Wales.
# NGED South Wales (7): South Wales.
# ---------------------------------------------------------------------------

_WAL_LAD_TO_DNO: dict[str, str] = {
    # --- SP Manweb ---
    "W06000001": "SP Manweb",              # Isle of Anglesey
    "W06000002": "SP Manweb",              # Gwynedd
    "W06000003": "SP Manweb",              # Conwy
    "W06000004": "SP Manweb",              # Denbighshire
    "W06000005": "SP Manweb",              # Flintshire
    "W06000006": "SP Manweb",              # Wrexham
    "W06000008": "SP Manweb",              # Ceredigion
    "W06000023": "SP Manweb",              # Powys

    # --- NGED South Wales ---
    "W06000009": "NGED South Wales",       # Pembrokeshire
    "W06000010": "NGED South Wales",       # Carmarthenshire
    "W06000011": "NGED South Wales",       # Swansea
    "W06000012": "NGED South Wales",       # Neath Port Talbot
    "W06000013": "NGED South Wales",       # Bridgend
    "W06000014": "NGED South Wales",       # Vale of Glamorgan
    "W06000015": "NGED South Wales",       # Cardiff
    "W06000016": "NGED South Wales",       # Rhondda Cynon Taf
    "W06000018": "NGED South Wales",       # Caerphilly
    "W06000019": "NGED South Wales",       # Blaenau Gwent
    "W06000020": "NGED South Wales",       # Torfaen
    "W06000021": "NGED South Wales",       # Monmouthshire
    "W06000022": "NGED South Wales",       # Newport
    "W06000024": "NGED South Wales",       # Merthyr Tydfil
}

# ---------------------------------------------------------------------------
# Post-2019 English boundary changes not yet in D4's crosswalk.
# DfT VEH0142 uses current geographies and backcasts them across the time
# series, so these new codes appear for both 2021 Q4 and 2024 Q4 data.
# The old constituent district codes are absent from VEH0142.
# ---------------------------------------------------------------------------

_NEW_ENG_LAD_TO_DNO: dict[str, str] = {
    # Created April 2020
    "E06000060": "SSEN (Southern Electric)",       # Buckinghamshire (was Aylesbury Vale/Chiltern/South Bucks/Wycombe)

    # Created April 2021
    "E06000065": "NGED East Midlands",             # West Northamptonshire (was Daventry/Northampton/South Northamptonshire)
    "E06000066": "NGED East Midlands",             # North Northamptonshire (was Corby/East Northamptonshire/Kettering/Wellingborough)

    # Created April 2023
    "E06000061": "Northern Powergrid (Yorkshire)", # North Yorkshire (was Craven/Hambleton/Harrogate/Richmondshire/Ryedale/Scarborough/Selby)
    "E06000062": "NGED South West",                # Somerset (was Mendip/Sedgemoor/Somerset West and Taunton/South Somerset)
    "E06000063": "Electricity North West",         # Cumberland (was Allerdale/Carlisle/Copeland)
    "E06000064": "Electricity North West",         # Westmorland and Furness (was Barrow-in-Furness/Eden/South Lakeland)
}

# Full GB crosswalk: 317 English (older) + 7 new English + 32 Scottish + 22 Welsh
LAD_TO_DNO_GB: dict[str, str] = {
    **_ENG_LAD_TO_DNO,
    **_NEW_ENG_LAD_TO_DNO,
    **_SCO_LAD_TO_DNO,
    **_WAL_LAD_TO_DNO,
}


# ---------------------------------------------------------------------------
# ODS parsing helpers
# ---------------------------------------------------------------------------

_T  = "{urn:oasis:names:tc:opendocument:xmlns:table:1.0}"
_TX = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"


def _cell_text(cell: ET.Element) -> str:
    return " ".join((p.text or "") for p in cell.iter(_TX + "p")).strip()


def _expand_row(row: ET.Element) -> list[str]:
    """Expand number-columns-repeated cells and strip trailing empties."""
    cells: list[str] = []
    for cell in row.findall(_T + "table-cell"):
        rep = int(cell.get(_T + "number-columns-repeated", 1))
        cells.extend([_cell_text(cell)] * rep)
    while cells and not cells[-1]:
        cells.pop()
    return cells


def parse_ev_counts(content: bytes) -> pd.DataFrame:
    """
    Parse VEH0142 ODS and return LAD-level plug-in car counts.

    Returns DataFrame with columns: ons_code, count_2024q4, count_2021q4.
    Counts are summed across BEV and PHEV fuel types (Keepership=Total).
    """
    LAD_PREFIXES = ("E06", "E07", "E08", "E09", "S12", "W06")

    with zipfile.ZipFile(io.BytesIO(content)) as z:
        root = ET.fromstring(z.read("content.xml"))

    sheet: ET.Element | None = None
    for t in root.findall(".//" + _T + "table"):
        if t.get(_T + "name") == SHEET_NAME:
            sheet = t
            break
    if sheet is None:
        raise ValueError(f"Sheet {SHEET_NAME!r} not found in VEH0142 ODS.")

    all_rows = sheet.findall(_T + "table-row")

    # Row index 4 = spreadsheet row 5 = header
    header   = _expand_row(all_rows[4])
    ons_col  = header.index("ONS Code")
    fuel_col = header.index("Fuel")
    body_col = header.index("BodyType")
    keep_col = header.index("Keepership")
    q24_col  = header.index(Q4_2024)
    q21_col  = header.index(Q4_2021)

    def _parse_int(val: str) -> int:
        val = val.replace(",", "").strip()
        if val in ("", "c", "-", ".."):
            return 0
        return int(float(val))

    lad_counts: dict[str, list[int]] = {}

    for row in all_rows[5:]:
        c = _expand_row(row)
        if len(c) <= q24_col:
            continue
        if c[body_col] != "Cars":
            continue
        if c[fuel_col] not in PLUG_IN_FUELS:
            continue
        if c[keep_col] != "Total":
            continue

        ons = c[ons_col] if ons_col < len(c) else ""
        if not any(ons.startswith(p) for p in LAD_PREFIXES):
            continue

        cnt_24 = _parse_int(c[q24_col])
        cnt_21 = _parse_int(c[q21_col] if q21_col < len(c) else "0")

        if ons not in lad_counts:
            lad_counts[ons] = [0, 0]
        lad_counts[ons][0] += cnt_24
        lad_counts[ons][1] += cnt_21

    df = pd.DataFrame(
        [(k, v[0], v[1]) for k, v in lad_counts.items()],
        columns=["ons_code", "count_2024q4", "count_2021q4"],
    )
    print(f"D3 | Parsed {len(df)} LAD rows (BEV+PHEV cars, Total keepership)")
    return df


# ---------------------------------------------------------------------------
# Pipeline steps
# ---------------------------------------------------------------------------

def fetch_ods() -> bytes:
    print("D3 | Fetching DfT VEH0142 (plug-in vehicles by local authority) ...")
    resp = requests.get(VEH0142_URL, timeout=60)
    resp.raise_for_status()
    print(f"D3 | Downloaded {len(resp.content) / 1024:.0f} KB")
    return resp.content


def map_to_dno(ev_df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate LAD EV counts to DNO level using the GB crosswalk."""
    unmapped = ev_df[~ev_df["ons_code"].isin(LAD_TO_DNO_GB)]["ons_code"].tolist()
    if unmapped:
        print(
            f"D3 | Warning: {len(unmapped)} LAD code(s) not in crosswalk "
            f"(skipped): {unmapped[:10]}"
        )

    ev_df = ev_df[ev_df["ons_code"].isin(LAD_TO_DNO_GB)].copy()
    ev_df["dno"] = ev_df["ons_code"].map(LAD_TO_DNO_GB)

    dno_agg = (
        ev_df.groupby("dno")[["count_2024q4", "count_2021q4"]]
        .sum()
        .reset_index()
    )
    dno_agg["region_id"] = dno_agg["dno"].map(DNO_REGION_ID)
    return dno_agg.sort_values("region_id").reset_index(drop=True)


def compute_growth(dno_agg: pd.DataFrame) -> pd.DataFrame:
    """Compute (count_2024q4 - count_2021q4) / count_2021q4 per DNO."""
    df = dno_agg.copy()

    zero_base = df[df["count_2021q4"] == 0]["dno"].tolist()
    if zero_base:
        raise ValueError(
            f"Zero 2021Q4 EV count for DNO(s) {zero_base} — cannot compute growth. "
            "Check crosswalk coverage."
        )

    df["growth_metric"] = (
        (df["count_2024q4"] - df["count_2021q4"]) / df["count_2021q4"]
    ).round(6)

    print(
        f"D3 | Growth range: {df['growth_metric'].min():.3f} to "
        f"{df['growth_metric'].max():.3f}  "
        f"({df.loc[df['growth_metric'].idxmin(), 'dno']} to "
        f"{df.loc[df['growth_metric'].idxmax(), 'dno']})"
    )
    return df


def normalise(df: pd.DataFrame) -> pd.DataFrame:
    """Standard min-max: higher growth_metric = higher d3_score."""
    x = df["growth_metric"]
    x_min, x_max = x.min(), x.max()
    df = df.copy()
    if x_max == x_min:
        df["d3_score"] = 0.5
    else:
        df["d3_score"] = ((x - x_min) / (x_max - x_min)).round(6)
    return df


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run() -> pd.DataFrame:
    """Fetch, parse, aggregate, and persist D3 demand growth scores."""
    content = fetch_ods()
    ev_df   = parse_ev_counts(content)
    dno_agg = map_to_dno(ev_df)
    dno_agg = compute_growth(dno_agg)
    dno_agg = normalise(dno_agg)

    df_out = dno_agg[["dno", "region_id", "growth_metric", "d3_score"]]

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df_out.to_csv(OUTPUT_PATH, index=False)
    print(f"D3 | Saved {len(df_out)} DNO zones -> {OUTPUT_PATH.relative_to(PROJECT_ROOT)}")
    return df_out


if __name__ == "__main__":
    result = run()
    print()
    print(result.to_string(index=False))
