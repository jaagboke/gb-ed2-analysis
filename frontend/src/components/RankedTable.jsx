import { useEffect, useRef } from 'react'
import './RankedTable.css'

const DIM_META = [
  { key: 'd1', label: 'D1', color: 'var(--dim-d1)', title: 'Renewable Headroom' },
  { key: 'd2', label: 'D2', color: 'var(--dim-d2)', title: 'Grid Constraints' },
  { key: 'd3', label: 'D3', color: 'var(--dim-d3)', title: 'Demand Growth' },
  { key: 'd4', label: 'D4', color: 'var(--dim-d4)', title: 'Socioeconomic Vulnerability' },
  { key: 'd5', label: 'D5', color: 'var(--dim-d5)', title: 'Carbon Intensity' },
]

function DimBars({ scores, d4Pending }) {
  return (
    <div className="dim-bars">
      {DIM_META.map(d => {
        const val    = scores[d.key] ?? 0
        const isPend = d.key === 'd4' && d4Pending
        return (
          <div
            key={d.key}
            className="dim-bar-row"
            title={`${d.title}: ${(val * 100).toFixed(0)}%${isPend ? ' (pending)' : ''}`}
          >
            <span className="dim-bar-key">{d.label}</span>
            <div className="dim-bar-track">
              <div
                className="dim-bar-fill"
                style={{
                  width: `${val * 100}%`,
                  background: d.color,
                  opacity: isPend ? 0.25 : 1,
                }}
              />
            </div>
          </div>
        )
      })}
    </div>
  )
}

function CompositeBar({ value }) {
  // Interpolate #E8F5E9 → #1B5E20
  const s = Math.max(0, Math.min(1, value))
  const r = Math.round(232 + (27 - 232) * s)
  const g = Math.round(245 + (94 - 245) * s)
  const b = Math.round(233 + (32 - 233) * s)
  const color = `rgb(${r},${g},${b})`

  return (
    <div className="composite-cell">
      <div className="composite-bar-track">
        <div
          className="composite-bar-fill"
          style={{ width: `${s * 100}%`, background: color }}
        />
      </div>
      <span className="composite-num">{value.toFixed(3)}</span>
    </div>
  )
}

function SkeletonRows() {
  return (
    <>
      {Array.from({ length: 14 }, (_, i) => (
        <tr key={i} className="table-row-skeleton">
          <td><div className="sk sk-rank" /></td>
          <td><div className="sk sk-name" style={{ width: `${80 + (i % 4) * 15}px` }} /></td>
          <td><div className="sk sk-score" /></td>
          <td><div className="sk sk-bars" /></td>
        </tr>
      ))}
    </>
  )
}

export default function RankedTable({ zones, loading, selectedDno }) {
  const rowRefs = useRef({})

  // When a zone is selected on the map, scroll it into view in this panel.
  useEffect(() => {
    if (!selectedDno) return
    const el = rowRefs.current[selectedDno]
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }, [selectedDno])

  return (
    <div className="ranked-table-panel">
      <div className="ranked-table-header">
        <span className="ranked-table-title">Rankings</span>
        <span className="ranked-table-count">{zones.length ? `${zones.length} zones` : ''}</span>
      </div>

      <div className="ranked-table-scroll">
        <table className="ranked-table">
          <thead>
            <tr>
              <th className="col-rank">#</th>
              <th className="col-name">DNO Zone</th>
              <th className="col-score">Score</th>
              <th className="col-dims">D1–D5</th>
            </tr>
          </thead>
          <tbody>
            {loading && !zones.length
              ? <SkeletonRows />
              : zones.map(zone => (
                  <tr
                    key={zone.dno}
                    ref={el => { if (el) rowRefs.current[zone.dno] = el }}
                    className={`table-row${zone.dno === selectedDno ? ' table-row-selected' : ''}`}
                  >
                    <td className="col-rank">
                      <span className={`rank-badge${zone.rank <= 3 ? ' rank-top' : ''}`}>
                        {zone.rank}
                      </span>
                    </td>

                    <td className="col-name">
                      <div className="zone-name">{zone.dno}</div>
                      {zone.d4_pending && (
                        <div
                          className="d4-pending-note"
                          title="D4 score is 0.0 — Scotland/Wales deprivation data pending"
                        >
                          D4 data pending
                        </div>
                      )}
                    </td>

                    <td className="col-score">
                      <CompositeBar value={zone.composite} />
                    </td>

                    <td className="col-dims">
                      <DimBars scores={zone.scores} d4Pending={zone.d4_pending} />
                    </td>
                  </tr>
                ))
            }
          </tbody>
        </table>
      </div>

      <div className="dim-legend">
        {DIM_META.map(d => (
          <span key={d.key} className="dim-legend-item" title={d.title}>
            <span className="dim-legend-dot" style={{ background: d.color }} />
            {d.label}
          </span>
        ))}
      </div>
    </div>
  )
}
