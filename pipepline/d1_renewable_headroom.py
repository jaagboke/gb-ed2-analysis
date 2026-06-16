"""
D1 - Renewable Headroom
=======================
Measures available capacity for new renewable generation connections per DNO
licence area, using the RIIO-ED2 Time to Connect (TtC) performance metric as
a proxy for connection queue pressure and network headroom.

Rationale
---------
Ofgem's RIIO-ED2 framework incentivises each DNO to reduce the time taken to
connect customers to the network. The TtC metric is measured in working days
from application to energisation. Longer TtC indicates:
  - Higher volumes of pending connection applications (queue backlog)
  - Greater need for network reinforcement before connecting new generation
  - Lower remaining available capacity for new renewable connections

Neither per-DNO connection queue volumes nor acceptance/rejection rates are
available as machine-readable open data. TtC is the closest publicly
available proxy that captures connection queue pressure at DNO level.

Source
------
Ofgem RIIO-2 Electricity Distribution Annual Report 2023-24 – Supplementary
Data File (XLSM), sheet 'Ch2 outputs - connections'.

URL  : https://www.ofgem.gov.uk/sites/default/files/2025-04/
       RIIO-2%20Electricity%20Distribution%20Annual%20Report%202023%20to%20
       2024%20-%20supplementary%20data%20file.xlsm

Metric
------
LVSSB Time to Connect (2023/24, working days).

LVSSB (Low Voltage Simple Scheme B) covers larger LV and simple HV
connections — the category most representative of distributed renewable
generation projects up to ~1 MW. The data is drawn from live RIIO-ED2
regulatory submissions and is the most granular per-DNO connection
performance indicator published by Ofgem.

Direction : Shorter TtC = faster connections = less congested = more headroom
            = HIGHER D1 score.
            Standard min-max:  D_norm = 1 - (TtC - TtC_min)/(TtC_max - TtC_min)
            (inverted because lower TtC is better)

Parsed using the XLSX ZIP structure (zipfile + xml.etree) to avoid openpyxl
macro-handling issues with .xlsm files.

Output columns
--------------
dno                  DNO licence area name
region_id            NESO carbon-intensity region ID (1-14)
ttc_lvssb_days       LVSSB Time to Connect, 2023/24 (working days)
d1_score             Normalised score 0-1  (higher = more headroom)
"""

from __future__ import annotations

import io
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import pandas as pd
import requests

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

XLSM_URL = (
    "https://www.ofgem.gov.uk/sites/default/files/2025-04/"
    "RIIO-2%20Electricity%20Distribution%20Annual%20Report%202023%20to%20"
    "2024%20-%20supplementary%20data%20file.xlsm"
)

SHEET_NAME = "Ch2 outputs - connections"

# Rows and columns for the 2023/24 LVSSB TtC table.
# Determined from the 'Ch2 outputs - connections' sheet structure:
#   Col D = DNO code   Col K = LVSSB Time to Connect (working days)
# DNO rows run from 39 to 52 (14 DNOs, one per row).
DNO_COL   = "D"    # Ofgem short code (ENWL, NPgN, …)
TTC_COL   = "K"    # LVSSB Time to Connect, 2023/24
ROW_START = 39
ROW_END   = 52

# Maps Ofgem RIIO-ED2 DNO short codes to (region_id, canonical DNO name).
# Source: Ofgem licence register and NESO Carbon Intensity API convention.
DNO_CODE_MAP: dict[str, tuple[int, str]] = {
    "SSEH":   (1,  "SSEN (Scottish Hydro)"),
    "SPD":    (2,  "SP Distribution"),
    "ENWL":   (3,  "Electricity North West"),
    "NPgN":   (4,  "Northern Powergrid (Northeast)"),
    "NPgY":   (5,  "Northern Powergrid (Yorkshire)"),
    "SPMW":   (6,  "SP Manweb"),
    "SWALES": (7,  "NGED South Wales"),
    "WMID":   (8,  "NGED West Midlands"),
    "EMID":   (9,  "NGED East Midlands"),
    "EPN":    (10, "UKPN East of England"),
    "SWEST":  (11, "NGED South West"),
    "SSES":   (12, "SSEN (Southern Electric)"),
    "LPN":    (13, "UKPN London"),
    "SPN":    (14, "UKPN South East"),
}

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PATH  = PROJECT_ROOT / "data" / "zones_d1_headroom.csv"


# ---------------------------------------------------------------------------
# XLSM parsing helpers
# ---------------------------------------------------------------------------

def _col_letter_to_index(letter: str) -> int:
    """Convert an Excel column letter (A, B, …, Z, AA, …) to a 1-based index."""
    result = 0
    for ch in letter.upper():
        result = result * 26 + (ord(ch) - ord("A") + 1)
    return result


def _cell_col(ref: str) -> str:
    """Extract the column letter(s) from a cell reference like 'K39'."""
    return "".join(ch for ch in ref if ch.isalpha())


def _cell_row(ref: str) -> int:
    """Extract the row number from a cell reference like 'K39'."""
    return int("".join(ch for ch in ref if ch.isdigit()))


def parse_ttc_from_xlsm(content: bytes) -> dict[str, float]:
    """
    Parse LVSSB TtC values per DNO from the Ofgem RIIO-ED2 supplementary XLSM.

    Reads the XLSX ZIP structure directly (works with .xlsm files which openpyxl
    may mishandle due to embedded VBA macros).

    Returns {dno_code: ttc_days} for the 14 DNOs (rows ROW_START – ROW_END).
    """
    NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    REL_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"

    with zipfile.ZipFile(io.BytesIO(content)) as z:
        # --- shared strings ---
        ss_root = ET.fromstring(z.read("xl/sharedStrings.xml"))
        strings: list[str] = []
        for si in ss_root.findall(f"{NS}si"):
            parts = [t.text or "" for t in si.findall(f".//{NS}t")]
            strings.append("".join(parts))

        # --- find worksheet file for our target sheet ---
        wb_root  = ET.fromstring(z.read("xl/workbook.xml"))
        rel_root = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        rel_map  = {r.get("Id"): r.get("Target") for r in rel_root}

        sheet_file: str | None = None
        for sheet in wb_root.findall(f".//{NS}sheet"):
            if sheet.get("name") == SHEET_NAME:
                rid = sheet.get(f"{REL_NS}id")
                sheet_file = rel_map[rid].replace("worksheets/", "")
                break

        if sheet_file is None:
            raise ValueError(
                f"Sheet {SHEET_NAME!r} not found in XLSM. "
                "The Ofgem file structure may have changed."
            )

        # --- read the target rows ---
        ws_root = ET.fromstring(z.read(f"xl/worksheets/{sheet_file}"))

        dno_col_idx = _col_letter_to_index(DNO_COL)
        ttc_col_idx = _col_letter_to_index(TTC_COL)

        result: dict[str, float] = {}
        for row in ws_root.findall(f"{NS}sheetData/{NS}row"):
            rnum = int(row.get("r", 0))
            if rnum < ROW_START or rnum > ROW_END:
                continue

            row_data: dict[int, str] = {}
            for cell in row.findall(f"{NS}c"):
                ref = cell.get("r", "")
                t   = cell.get("t", "")
                v   = cell.find(f"{NS}v")
                if v is None or v.text is None:
                    continue
                col_idx = _col_letter_to_index(_cell_col(ref))
                row_data[col_idx] = (
                    strings[int(v.text)] if t == "s" else v.text
                )

            dno_code = row_data.get(dno_col_idx, "").strip()
            ttc_raw  = row_data.get(ttc_col_idx, "")
            if dno_code and ttc_raw:
                try:
                    result[dno_code] = float(ttc_raw)
                except ValueError:
                    pass

    return result


# ---------------------------------------------------------------------------
# Pipeline steps
# ---------------------------------------------------------------------------

def fetch_xlsm() -> bytes:
    """Download the Ofgem RIIO-ED2 2023-24 supplementary XLSM file."""
    print("D1 | Fetching Ofgem RIIO-ED2 2023-24 supplementary data file ...")
    resp = requests.get(XLSM_URL, timeout=30)
    resp.raise_for_status()
    print(f"D1 | Downloaded {len(resp.content) / 1024:.0f} KB")
    return resp.content


def build_dno_frame(ttc_map: dict[str, float]) -> pd.DataFrame:
    """
    Map parsed TtC values to canonical DNO names and region_ids.
    Validates all 14 DNOs are present.
    """
    missing = set(DNO_CODE_MAP) - set(ttc_map)
    if missing:
        raise ValueError(
            f"Missing TtC data for DNO code(s): {sorted(missing)}. "
            "The sheet structure may have changed."
        )

    rows = []
    for code, (region_id, dno) in DNO_CODE_MAP.items():
        rows.append({
            "dno":             dno,
            "region_id":       region_id,
            "ttc_lvssb_days":  round(ttc_map[code], 2),
        })

    df = pd.DataFrame(rows).sort_values("region_id").reset_index(drop=True)
    print(
        f"D1 | TtC range: {df['ttc_lvssb_days'].min():.1f}–"
        f"{df['ttc_lvssb_days'].max():.1f} working days "
        f"({df.loc[df['ttc_lvssb_days'].idxmin(), 'dno']} to "
        f"{df.loc[df['ttc_lvssb_days'].idxmax(), 'dno']})"
    )
    return df


def normalise(df: pd.DataFrame) -> pd.DataFrame:
    """
    Inverted min-max normalise ttc_lvssb_days → d1_score (0–1).
    Shorter TtC = faster connections = less queue = more headroom = HIGHER score.
    Formula: D_norm = 1 - (TtC - TtC_min) / (TtC_max - TtC_min)
    """
    x = df["ttc_lvssb_days"]
    x_min, x_max = x.min(), x.max()
    df = df.copy()
    if x_max == x_min:
        df["d1_score"] = 0.5
    else:
        df["d1_score"] = (1 - (x - x_min) / (x_max - x_min)).round(6)
    return df


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run() -> pd.DataFrame:
    """Fetch, parse, normalise, and persist D1 headroom scores."""
    content = fetch_xlsm()
    ttc_map = parse_ttc_from_xlsm(content)
    print(f"D1 | Parsed TtC for {len(ttc_map)} DNOs: {sorted(ttc_map)}")

    df = build_dno_frame(ttc_map)
    df = normalise(df)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUTPUT_PATH, index=False)
    print(f"D1 | Saved {len(df)} DNO zones -> {OUTPUT_PATH.relative_to(PROJECT_ROOT)}")
    return df


if __name__ == "__main__":
    result = run()
    print()
    print(result.to_string(index=False))
