"""
GB Green Energy Investment Prioritisation Tool - Flask API
===========================================================
Serves scored DNO zone data and supports custom WADD composite scoring
via query-parameter weights for the five investment dimensions (D1-D5).

Endpoints
---------
GET /api/health
GET /api/zones
GET /api/scores?d1=0.20&d2=0.20&d3=0.20&d4=0.20&d5=0.20
GET /api/scenarios
GET /api/methodology

Run
---
  From project root:  python app/backend.py
  Flask CLI:          flask --app app.backend run --port 5000
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure project root is on the path so scoring.engine is importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import math
from typing import Any

import pandas as pd
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

from scoring.engine import SCENARIOS, load_dimensions

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = Flask(__name__)
CORS(app)

FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"

# ---------------------------------------------------------------------------
# Data loading — happens once at import time
# ---------------------------------------------------------------------------

DATA_DIR = PROJECT_ROOT / "data"

_DIMENSION_FILES = {
    "d1": DATA_DIR / "zones_d1_headroom.csv",
    "d2": DATA_DIR / "zones_d2_constraints.csv",
    "d3": DATA_DIR / "zones_d3_demand.csv",
    "d4": DATA_DIR / "zones_d4_vulnerability.csv",
    "d5": DATA_DIR / "zones_d5_carbon.csv",
}

_ZONES_DF: pd.DataFrame | None = None
_LOAD_ERROR: str | None = None


def _load_zone_data() -> tuple[pd.DataFrame | None, str | None]:
    """
    Load and merge all five dimension CSVs into a single rich DataFrame.

    Returns (dataframe, None) on success, (None, error_message) on failure.
    Raw metric columns are included alongside normalised scores so the API
    can serve both to the frontend.
    """
    try:
        # Base merged frame: region_id + d1..d5 scores (via scoring engine)
        base = load_dimensions()  # 14 rows x [dno, region_id, d1_score..d5_score]

        # Augment with raw metric columns from individual CSVs
        raw_cols: dict[str, list[str]] = {
            "d1": ["ttc_lvssb_days"],
            "d2": ["binding_boundary", "constraint_metric"],
            "d3": ["growth_metric"],
            "d4": ["deprivation_pctile_wtd"],
            "d5": ["intensity_gco2_kwh"],
        }

        merged = base.copy()
        for dim, cols in raw_cols.items():
            src = pd.read_csv(_DIMENSION_FILES[dim])
            keep = ["dno"] + [c for c in cols if c in src.columns]
            merged = merged.merge(src[keep], on="dno", how="left")

        # Convert growth_metric from ratio (e.g. 2.4) to percentage for display
        if "growth_metric" in merged.columns:
            merged["d3_growth_pct"] = (merged["growth_metric"] * 100).round(1)
            merged = merged.drop(columns=["growth_metric"])

        merged = merged.sort_values("region_id").reset_index(drop=True)
        return merged, None

    except FileNotFoundError as exc:
        return None, f"Data file not found: {exc}"
    except Exception as exc:  # noqa: BLE001
        return None, f"Failed to load zone data: {exc}"


_ZONES_DF, _LOAD_ERROR = _load_zone_data()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _data_ready() -> tuple[bool, Any]:
    """Return (True, None) if data is loaded, (False, error_response) if not."""
    if _ZONES_DF is None:
        return False, (
            jsonify({"error": "Data not loaded", "detail": _LOAD_ERROR}),
            503,
        )
    return True, None


def _parse_weights() -> tuple[dict[str, float] | None, Any]:
    """
    Parse d1..d5 weight query parameters.

    Returns (weights_dict, None) on success,
            (None, error_response_tuple) on validation failure.
    """
    weights: dict[str, float] = {}
    for dim in ("d1", "d2", "d3", "d4", "d5"):
        raw = request.args.get(dim)
        if raw is None:
            return None, (
                jsonify({
                    "error": f"Missing weight parameter '{dim}'",
                    "detail": (
                        "Provide all five weights as query parameters: "
                        "?d1=0.20&d2=0.20&d3=0.20&d4=0.20&d5=0.20"
                    ),
                }),
                400,
            )
        try:
            val = float(raw)
        except ValueError:
            return None, (
                jsonify({"error": f"Invalid weight for '{dim}': {raw!r} is not a number"}),
                400,
            )
        if not (0.0 <= val <= 1.0):
            return None, (
                jsonify({"error": f"Weight for '{dim}' must be between 0 and 1, got {val}"}),
                400,
            )
        weights[dim] = val

    total = sum(weights.values())
    if abs(total - 1.0) > 0.005:
        return None, (
            jsonify({
                "error": "Weights must sum to 1.0",
                "detail": f"Provided weights sum to {total:.4f}",
                "weights": weights,
            }),
            400,
        )

    return weights, None


def _compute_composite(df: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    """Compute WADD composite score from the five normalised dimension scores."""
    return (
        weights["d1"] * df["d1_score"]
        + weights["d2"] * df["d2_score"]
        + weights["d3"] * df["d3_score"]
        + weights["d4"] * df["d4_score"]
        + weights["d5"] * df["d5_score"]
    ).round(6)


def _zone_record(row: pd.Series) -> dict:
    """Convert a DataFrame row to a clean JSON-serialisable dict."""

    def _safe(val: Any) -> Any:
        if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
            return None
        if hasattr(val, "item"):  # numpy scalar
            return val.item()
        return val

    record: dict[str, Any] = {
        "dno":       row["dno"],
        "region_id": int(row["region_id"]),
        "scores": {
            "d1": _safe(row["d1_score"]),
            "d2": _safe(row["d2_score"]),
            "d3": _safe(row["d3_score"]),
            "d4": _safe(row["d4_score"]),
            "d5": _safe(row["d5_score"]),
        },
        "metrics": {
            "d1_ttc_days":              _safe(row.get("ttc_lvssb_days")),
            "d2_binding_boundary":      _safe(row.get("binding_boundary")),
            "d2_constraint_mw":         _safe(row.get("constraint_metric")),
            "d3_growth_pct":            _safe(row.get("d3_growth_pct")),
            "d4_deprivation_pctile_wtd": _safe(row.get("deprivation_pctile_wtd")),
            "d5_intensity_gco2kwh":     _safe(row.get("intensity_gco2_kwh")),
        },
    }
    return record


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/api/health")
def health():
    """Liveness check — returns current data-load status."""
    if _ZONES_DF is not None:
        return jsonify({
            "status":       "ok",
            "zones_loaded": len(_ZONES_DF),
            "dimensions":   5,
        })
    return jsonify({
        "status": "degraded",
        "error":  _LOAD_ERROR,
    }), 503


@app.get("/api/zones")
def zones():
    """
    Return all 14 DNO zones with their dimension scores and raw metric values.

    Response shape:
        { "count": 14, "zones": [ { dno, region_id, scores, metrics }, ... ] }
    """
    ready, err = _data_ready()
    if not ready:
        return err

    records = [_zone_record(row) for _, row in _ZONES_DF.iterrows()]
    return jsonify({"count": len(records), "zones": records})


@app.get("/api/scores")
def scores():
    """
    Compute and return zones ranked by a custom WADD composite score.

    Query parameters: d1, d2, d3, d4, d5  (floats summing to 1.0)

    Response shape:
        {
          "weights": { d1..d5 },
          "count": 14,
          "zones": [
            { rank, dno, region_id, composite, scores, metrics },
            ...
          ]   (sorted composite descending — rank 1 is most investable)
        }
    """
    ready, err = _data_ready()
    if not ready:
        return err

    weights, err = _parse_weights()
    if weights is None:
        return err

    df = _ZONES_DF.copy()
    df["composite"] = _compute_composite(df, weights)
    df = df.sort_values("composite", ascending=False).reset_index(drop=True)
    df["rank"] = range(1, len(df) + 1)

    records = []
    for _, row in df.iterrows():
        rec = _zone_record(row)
        rec["rank"]      = int(row["rank"])
        rec["composite"] = round(float(row["composite"]), 6)
        records.append(rec)

    return jsonify({
        "weights": weights,
        "count":   len(records),
        "zones":   records,
    })


@app.get("/api/scenarios")
def scenarios():
    """
    Return the three predefined weight scenarios.

    Response shape:
        { "scenarios": [ { id, name, description, weights }, ... ] }
    """
    scenario_meta = {
        "s1": {
            "name":        "Equal Weights",
            "description": (
                "Neutral baseline. All five dimensions are weighted equally at 0.20. "
                "No a priori preference between renewable headroom, grid constraints, "
                "demand growth, socioeconomic vulnerability, or carbon intensity."
            ),
        },
        "s2": {
            "name":        "Investor-Focused",
            "description": (
                "Reflects a commercial renewable developer perspective. "
                "D1 (renewable headroom) and D2/D3 (grid constraints and demand growth) "
                "receive the highest weights. Socioeconomic vulnerability (D4) is "
                "de-prioritised relative to connection feasibility."
            ),
        },
        "s3": {
            "name":        "Just Transition",
            "description": (
                "Reflects a policy or social infrastructure investor perspective. "
                "D4 (socioeconomic vulnerability) receives the highest weight (0.35), "
                "capturing the principle that investment should prioritise areas where "
                "affordable clean energy access matters most."
            ),
        },
    }

    output = []
    for sid, weights in SCENARIOS.items():
        meta = scenario_meta[sid]
        output.append({
            "id":          sid,
            "name":        meta["name"],
            "description": meta["description"],
            "weights": {
                "d1": weights[0],
                "d2": weights[1],
                "d3": weights[2],
                "d4": weights[3],
                "d5": weights[4],
            },
        })

    return jsonify({"scenarios": output})


@app.get("/api/methodology")
def methodology():
    """
    Return a structured summary of the scoring methodology.

    Derived from methodology/methodology_spec.docx (Phase 1 deliverable).
    """
    return jsonify({
        "title":   "GB Green Energy Investment Prioritisation Tool",
        "version": "1.0",
        "date":    "June 2026",
        "framework": {
            "name":    "Weighted Additive Model (WADD)",
            "formula": "Score(z) = w1·D1(z) + w2·D2(z) + w3·D3(z) + w4·D4(z) + w5·D5(z)",
            "rationale": (
                "WADD is selected over TOPSIS, ELECTRE, and AHP on the grounds of "
                "transparency, reproducibility, and interpretability for a policy-facing "
                "audience. Weights are treated as explicit value judgements rather than "
                "hidden assumptions."
            ),
        },
        "normalisation": {
            "method":   "Min-max scaling to 0–1 range across the 14 DNO zones",
            "standard": "D_norm = (x – x_min) / (x_max – x_min)",
            "inverted": (
                "D_norm = 1 – (x – x_min) / (x_max – x_min) "
                "for inverse dimensions (D1, D2) where lower raw value = better"
            ),
        },
        "dimensions": [
            {
                "id":          "d1",
                "name":        "Renewable Headroom",
                "definition":  (
                    "Available grid capacity for new renewable connections, measured "
                    "via RIIO-ED2 LVSSB Time to Connect (working days). "
                    "Shorter TtC = less queue pressure = more headroom."
                ),
                "source":      "Ofgem RIIO-ED2 2023-24 Supplementary Data File",
                "direction":   "Higher score = more headroom (shorter TtC, inverted)",
                "metric":      "LVSSB Time to Connect (working days)",
            },
            {
                "id":          "d2",
                "name":        "Grid Constraint Severity",
                "definition":  (
                    "Transmission boundary constraint limit (MW). Lower limits indicate "
                    "more congested boundaries, representing more severe constraints "
                    "on renewable dispatch."
                ),
                "source":      "NESO 24-month Constraint Limits (Open Data Portal)",
                "direction":   "Higher score = more constrained (lower limit MW, inverted)",
                "metric":      "Constraint limit MW at binding transmission boundary",
            },
            {
                "id":          "d3",
                "name":        "Demand Growth Trajectory",
                "definition":  (
                    "3-year relative growth in licensed plug-in cars (BEV + PHEV) "
                    "2021 Q4 to 2024 Q4, aggregated across constituent LADs per DNO zone."
                ),
                "source":      "DfT VEH0142 — Licensed plug-in vehicles by local authority",
                "direction":   "Higher score = faster EV adoption growth",
                "metric":      "Relative growth rate: (count_2024Q4 – count_2021Q4) / count_2021Q4",
            },
            {
                "id":          "d4",
                "name":        "Socioeconomic Vulnerability",
                "definition":  (
                    "Population-weighted mean deprivation percentile aggregated to DNO "
                    "zone level. Each nation's raw deprivation index is converted to a "
                    "0-100 percentile rank within its own distribution before aggregation, "
                    "making scores comparable across GB. Captures the just transition "
                    "dimension: higher deprivation zones have greater need for affordable "
                    "clean energy access."
                ),
                "source":      (
                    "England: DLUHC IMD 2019 File 7 (LSOA level, 32,844 areas). "
                    "Scotland: SIMD 2020v2 data zone look-up (6,976 data zones). "
                    "Wales: WIMD 2019 index and domain ranks (1,909 LSOAs)."
                ),
                "direction":   "Higher score = higher deprivation = greater investment need",
                "metric":      "Population-weighted mean harmonised deprivation percentile (0-100)",
                "caveat":      (
                    "Cross-national harmonisation converts each index to within-nation "
                    "percentile ranks. This captures relative deprivation within each "
                    "nation but does not reflect absolute deprivation differences between "
                    "nations. Welsh LSOAs use uniform population weights (WIMD 2019 does "
                    "not publish LSOA-level population)."
                ),
            },
            {
                "id":          "d5",
                "name":        "Carbon Intensity",
                "definition":  (
                    "Average grid carbon intensity (gCO2eq/kWh) for the DNO zone "
                    "derived from NESO regional carbon intensity data. Higher intensity "
                    "zones offer greater marginal abatement value from renewable investment."
                ),
                "source":      "NESO Carbon Intensity API (api.carbonintensity.org.uk)",
                "direction":   "Higher score = higher carbon intensity = more abatement potential",
                "metric":      "Grid carbon intensity in gCO2eq/kWh (live snapshot)",
            },
        ],
        "limitations": [
            "DNO zone boundaries do not correspond to Local Authority geographies; spatial aggregation introduces approximation error.",
            "RIIO-ED2 TtC data reflects regulatory averages, not real-time network conditions.",
            "The model is static: zones are scored at a point in time rather than over a trajectory.",
            "D4 cross-national harmonisation uses within-nation percentile ranks; this captures relative but not absolute deprivation differences between England, Scotland, and Wales.",
            "The WADD model assumes linear preferences and no interaction effects between dimensions.",
        ],
        "bibliography": [
            "Wang et al. (2009). Review on multi-criteria decision analysis aid in sustainable energy. Renewable and Sustainable Energy Reviews, 13(9).",
            "Ofgem (2022). RIIO-ED2 Final Determinations.",
            "NESO (2024). Carbon Intensity API Documentation.",
            "Grantham Research Institute (LSE, 2019). Investing in a just transition in the UK.",
            "Arup / Cambridge Econometrics (2026). Gridunlocked: Unlocking the benefits of investing in the electricity grid.",
        ],
    })


# ---------------------------------------------------------------------------
# React SPA — serve built frontend for all non-API routes
# ---------------------------------------------------------------------------

@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve_react(path):
    """
    Serve the React SPA.  Static assets (JS/CSS) are returned directly;
    everything else (including unknown paths) returns index.html so that
    React Router can handle client-side navigation.
    """
    if not FRONTEND_DIST.is_dir():
        return jsonify({
            "error": "Frontend not built",
            "detail": "Run:  cd frontend && npm run build",
        }), 503

    target = FRONTEND_DIST / path
    if path and target.is_file():
        return send_from_directory(str(FRONTEND_DIST), path)

    return send_from_directory(str(FRONTEND_DIST), "index.html")


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------

@app.errorhandler(404)
def not_found(exc):
    return jsonify({
        "error": "Not found",
        "detail": f"{request.method} {request.path} is not a valid endpoint",
        "available_endpoints": [
            "GET /api/health",
            "GET /api/zones",
            "GET /api/scores?d1=0.20&d2=0.20&d3=0.20&d4=0.20&d5=0.20",
            "GET /api/scenarios",
            "GET /api/methodology",
        ],
    }), 404


@app.errorhandler(405)
def method_not_allowed(exc):
    return jsonify({
        "error": "Method not allowed",
        "detail": f"{request.method} is not supported on {request.path}",
    }), 405


@app.errorhandler(500)
def internal_error(exc):
    return jsonify({
        "error":  "Internal server error",
        "detail": str(exc),
    }), 500


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if _LOAD_ERROR:
        print(f"[WARNING] Data failed to load: {_LOAD_ERROR}")
        print("[WARNING] /api/zones and /api/scores will return 503 until fixed.")
    else:
        print(f"[OK] Loaded {len(_ZONES_DF)} DNO zones across 5 dimensions.")

    app.run(host="0.0.0.0", port=5000, debug=True)
