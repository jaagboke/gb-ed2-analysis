# GB Green Energy Investment Prioritisation Tool

A data-driven tool for ranking Great Britain's 14 Distribution Network Operator (DNO) zones by their attractiveness for green energy investment. Zones are scored across five dimensions using a Weighted Additive Decision (WADD) model, with three built-in weight scenarios and a fully interactive custom-weighting interface.

---

## What it does

- Scores all 14 GB DNO zones across five investment dimensions (D1–D5)
- Supports three predefined weight scenarios (Equal, Investor-Focused, Just Transition)
- Allows users to define custom dimension weights via an interactive slider interface
- Displays results on an interactive choropleth map and ranked table
- Exposes a REST API for programmatic access to scores and methodology

---

## The Five Dimensions

| # | Dimension | Source | Direction |
|---|-----------|--------|-----------|
| D1 | **Renewable Headroom** — available grid capacity for new connections, measured by RIIO-ED2 LVSSB Time to Connect (working days) | Ofgem RIIO-ED2 2023–24 Supplementary Data | Lower TtC → higher score |
| D2 | **Grid Constraint Severity** — transmission boundary constraint limits (MW); lower limits signal more congested boundaries | NESO 24-month Constraint Limits | Lower MW → higher score |
| D3 | **Demand Growth Trajectory** — 3-year relative growth in licensed plug-in vehicles (BEV + PHEV) at LAD level, aggregated to DNO zone | DfT VEH0142 Licensed plug-in vehicles by local authority | Higher growth → higher score |
| D4 | **Socioeconomic Vulnerability** — population-weighted mean deprivation percentile across all small areas in each DNO zone, harmonised across England (IMD 2019), Scotland (SIMD 2020v2), and Wales (WIMD 2019) | DLUHC / Scottish Government / Welsh Government | Higher deprivation → higher score |
| D5 | **Carbon Intensity** — average grid carbon intensity (gCO₂eq/kWh) by DNO zone; higher intensity zones offer greater marginal abatement value | NESO Carbon Intensity API | Higher intensity → higher score |

### Weight Scenarios

| Scenario | D1 | D2 | D3 | D4 | D5 | Focus |
|----------|----|----|----|----|-----|-------|
| S1 Equal | 0.20 | 0.20 | 0.20 | 0.20 | 0.20 | Neutral baseline |
| S2 Investor-Focused | 0.35 | 0.25 | 0.25 | 0.05 | 0.10 | Commercial renewable developer |
| S3 Just Transition | 0.15 | 0.15 | 0.20 | 0.35 | 0.15 | Policy / social infrastructure |

---

## Project Structure

```
gb-green-investment-tool/
├── app/
│   └── backend.py          # Flask REST API
├── data/
│   ├── dno_boundaries.geojson
│   ├── zones_d1_headroom.csv
│   ├── zones_d2_constraints.csv
│   ├── zones_d3_demand.csv
│   ├── zones_d4_vulnerability.csv
│   ├── zones_d5_carbon.csv
│   └── zones_ranked.csv    # Pre-computed scores (all three scenarios)
├── frontend/
│   ├── src/
│   │   ├── App.jsx
│   │   └── components/
│   └── vite.config.js
├── pipepline/
│   ├── d1_renewable_headroom.py
│   ├── d2_grid_constraints.py
│   ├── d3_demand_growth.py
│   ├── d4_vulnerability.py  # GB-wide: England + Scotland + Wales
│   └── d5_carbon_intensity.py
├── scoring/
│   └── engine.py           # WADD scoring model + CSV output
├── Dockerfile
├── render.yaml
└── requirements.txt
```

---

## Running Locally

### Prerequisites

- Python 3.11+
- Node.js 18+

### 1. Set up the Python environment

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Start the Flask API

```bash
python app/backend.py
# API available at http://localhost:5000
```

### 3. Start the frontend dev server

In a separate terminal:

```bash
cd frontend
npm install
npm run dev
# App available at http://localhost:5173
```

The Vite dev server proxies all `/api` requests to `localhost:5000`, so both servers must be running.

---

## Regenerating the Data

The `data/` CSVs are pre-built and committed to the repo. To refresh them from source:

```bash
# Run each pipeline in order (each writes its own CSV to data/)
python -m pipepline.d1_renewable_headroom
python -m pipepline.d2_grid_constraints
python -m pipepline.d3_demand_growth
python -m pipepline.d4_vulnerability
python -m pipepline.d5_carbon_intensity

# Recompute composite scores across all three scenarios
python -m scoring.engine
```

To evaluate a custom weight vector without writing to CSV:

```bash
python -m scoring.engine --weights 0.40 0.20 0.20 0.10 0.10
```

---

## API Reference

All endpoints return JSON.

| Endpoint | Description |
|----------|-------------|
| `GET /api/health` | Liveness check |
| `GET /api/zones` | All 14 DNO zones with dimension scores and raw metrics |
| `GET /api/scores?d1=0.20&d2=0.20&d3=0.20&d4=0.20&d5=0.20` | Zones ranked by custom WADD weights (must sum to 1.0) |
| `GET /api/scenarios` | Three predefined weight scenarios with metadata |
| `GET /api/methodology` | Full methodology description (sources, formula, limitations) |

---

## Deployment (Render)

The repo includes a `Dockerfile` and `render.yaml` for single-service deployment on [Render](https://render.com). Flask serves the pre-built React frontend as static files alongside the API.

**Steps:**

1. Push the repo to GitHub
2. Log in to Render → **New** → **Web Service**
3. Connect your GitHub repo — Render detects the `Dockerfile` automatically
4. Set plan to **Free** and deploy
5. Your public URL will be `https://<service-name>.onrender.com`

To build the frontend locally before deploying (optional — the Dockerfile does this automatically):

```bash
cd frontend
npm run build   # outputs to frontend/dist/
```

> **Note:** The free Render tier spins down after 15 minutes of inactivity. The first request after sleep takes ~30 seconds.

---

## Scoring Methodology

The WADD composite score for zone *z* is:

```
Score(z) = w₁·D1(z) + w₂·D2(z) + w₃·D3(z) + w₄·D4(z) + w₅·D5(z)
```

Each dimension is min-max normalised to [0, 1] across the 14 DNO zones before weighting. D1 and D2 are inverted (lower raw value = better outcome = higher score).

**Key limitations:**
- DNO boundaries do not align precisely with Local Authority geographies; spatial aggregation introduces some approximation error.
- D4 cross-national harmonisation converts each national index to within-nation percentile ranks, capturing relative but not absolute deprivation differences between England, Scotland, and Wales.
- The model is a static snapshot — zones are scored at a point in time rather than over a trajectory.

---

## Data Sources

- **Ofgem** — RIIO-ED2 2023–24 Annual Report Supplementary Data (D1)
- **NESO Open Data Portal** — 24-month Constraint Limits (D2)
- **DfT** — VEH0142 Licensed plug-in vehicles by local authority (D3)
- **DLUHC** — English Indices of Deprivation 2019, File 7 (D4)
- **Scottish Government** — SIMD 2020v2 data zone look-up (D4)
- **Welsh Government** — WIMD 2019 index and domain ranks (D4)
- **NESO Carbon Intensity API** — api.carbonintensity.org.uk (D5)
