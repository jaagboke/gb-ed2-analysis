import './WeightSliders.css'

const DIMS = [
  { key: 'd1', label: 'D1 Renewable Headroom',         color: 'var(--dim-d1)',
    hint: 'Connection queue speed (Ofgem RIIO-ED2 TtC)' },
  { key: 'd2', label: 'D2 Grid Constraints',            color: 'var(--dim-d2)',
    hint: 'Transmission boundary constraint severity' },
  { key: 'd3', label: 'D3 Demand Growth',               color: 'var(--dim-d3)',
    hint: 'EV adoption growth 2021→2024 (DfT VEH0142)' },
  { key: 'd4', label: 'D4 Socioeconomic Vulnerability', color: 'var(--dim-d4)',
    hint: 'Population-weighted IMD 2019 score' },
  { key: 'd5', label: 'D5 Carbon Intensity',            color: 'var(--dim-d5)',
    hint: 'Grid carbon intensity gCO₂/kWh (NESO)' },
]

const SCENARIOS = [
  {
    id: 's1',
    label: 'Equal',
    title: 'S1 — Equal Weights (0.20 each)',
  },
  {
    id: 's2',
    label: 'Investor',
    title: 'S2 — Investor-Focused (D1 0.35 / D2 0.25 / D3 0.25 / D4 0.05 / D5 0.10)',
  },
  {
    id: 's3',
    label: 'Just Transition',
    title: 'S3 — Just Transition (D1 0.15 / D2 0.15 / D3 0.20 / D4 0.35 / D5 0.15)',
  },
]

export default function WeightSliders({ weights, onChange, onScenario }) {
  const totalPct = Object.values(weights).reduce((s, v) => s + v, 0) * 100

  return (
    <div className="sliders-panel">
      <div className="sliders-section-title">Investment Weights</div>

      <div className="scenario-group">
        <div className="scenario-label">Presets</div>
        <div className="scenario-buttons">
          {SCENARIOS.map(s => (
            <button
              key={s.id}
              className="scenario-btn"
              title={s.title}
              onClick={() => onScenario(s.id)}
            >
              {s.label}
            </button>
          ))}
        </div>
      </div>

      <div className="sliders-list">
        {DIMS.map(dim => (
          <div key={dim.key} className="slider-card">
            <div className="slider-card-header">
              <div className="slider-card-name-row">
                <span
                  className="dim-dot"
                  style={{ background: dim.color }}
                />
                <span className="slider-name">{dim.label}</span>
              </div>
              <span className="slider-pct">
                {(weights[dim.key] * 100).toFixed(1)}%
              </span>
            </div>

            <input
              type="range"
              className="weight-slider"
              min="0"
              max="1"
              step="0.05"
              value={weights[dim.key]}
              style={{ '--thumb-color': dim.color, '--fill-pct': `${weights[dim.key] * 100}%` }}
              onChange={e => onChange(dim.key, parseFloat(e.target.value))}
            />

            <div className="slider-track-visual">
              <div
                className="slider-track-fill"
                style={{
                  width: `${weights[dim.key] * 100}%`,
                  background: dim.color,
                }}
              />
            </div>

            <div className="slider-hint">{dim.hint}</div>
          </div>
        ))}
      </div>

      <div className="weight-total">
        <span>Total</span>
        <span
          className="weight-total-value"
          style={{ color: Math.abs(totalPct - 100) < 0.5 ? 'var(--green-dark)' : '#C62828' }}
        >
          {totalPct.toFixed(1)}%
        </span>
      </div>

      <div className="methodology-note">
        Weights auto-normalise to sum to 100% · WADD scoring model
      </div>
    </div>
  )
}
