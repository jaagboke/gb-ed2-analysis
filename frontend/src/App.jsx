import { useState, useEffect, useCallback, useRef } from 'react'
import WeightSliders from './components/WeightSliders'
import ZoneVisualization from './components/ZoneVisualization'
import RankedTable from './components/RankedTable'
import './App.css'

const API = '/api'

const INITIAL_WEIGHTS = { d1: 0.2, d2: 0.2, d3: 0.2, d4: 0.2, d5: 0.2 }

function debounce(fn, ms) {
  let id
  const wrapped = (...args) => { clearTimeout(id); id = setTimeout(() => fn(...args), ms) }
  wrapped.cancel = () => clearTimeout(id)
  return wrapped
}

export default function App() {
  const [weights, setWeights]       = useState(INITIAL_WEIGHTS)
  const [zones, setZones]           = useState([])
  const [loading, setLoading]       = useState(true)
  const [apiError, setApiError]     = useState(null)
  const [selectedDno, setSelectedDno] = useState(null)

  // Fetch scored + ranked zones for the given weight vector
  const fetchScores = useCallback(async (w) => {
    try {
      const p = new URLSearchParams(
        Object.fromEntries(Object.entries(w).map(([k, v]) => [k, v.toFixed(8)]))
      )
      const res = await fetch(`${API}/scores?${p}`)
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body.error || `HTTP ${res.status}`)
      }
      const data = await res.json()
      setZones(data.zones)
      setApiError(null)
    } catch (err) {
      setApiError(err.message)
    } finally {
      setLoading(false)
    }
  }, [])

  const debouncedFetch = useRef(debounce(fetchScores, 280)).current

  useEffect(() => {
    setLoading(true)
    debouncedFetch(weights)
    return debouncedFetch.cancel
  }, [weights]) // eslint-disable-line react-hooks/exhaustive-deps

  // Proportional auto-normalisation: when dim `key` moves to `val`,
  // scale the remaining dims so all five always sum to 1.
  const handleWeightChange = useCallback((key, val) => {
    setWeights(prev => {
      const others = ['d1', 'd2', 'd3', 'd4', 'd5'].filter(d => d !== key)
      const otherSum = others.reduce((s, d) => s + prev[d], 0)
      const remaining = 1 - val
      const next = { ...prev, [key]: val }
      if (otherSum < 1e-9) {
        const each = remaining / others.length
        others.forEach(d => { next[d] = each })
      } else {
        others.forEach(d => { next[d] = (prev[d] / otherSum) * remaining })
      }
      return next
    })
  }, [])

  const handleScenario = useCallback((id) => {
    const presets = {
      s1: { d1: 0.20, d2: 0.20, d3: 0.20, d4: 0.20, d5: 0.20 },
      s2: { d1: 0.35, d2: 0.25, d3: 0.25, d4: 0.05, d5: 0.10 },
      s3: { d1: 0.15, d2: 0.15, d3: 0.20, d4: 0.35, d5: 0.15 },
    }
    setWeights(presets[id])
  }, [])

  return (
    <div className="app">
      <header className="app-header">
        <div className="header-inner">
          <div className="header-title-group">
            <h1 className="header-title">
              GB Green Energy Investment Prioritisation Tool
            </h1>
            <p className="header-subtitle">
              Multi-criteria analysis of DNO licence areas for renewable energy investment
            </p>
          </div>
          <div className="header-badge">MCDA · 14 Zones · 5 Dimensions</div>
        </div>
      </header>

      <div className="app-body">
        <aside className="panel panel-left">
          <WeightSliders
            weights={weights}
            onChange={handleWeightChange}
            onScenario={handleScenario}
          />
        </aside>

        <main className="panel panel-centre">
          {apiError && (
            <div className="error-banner">
              <span className="error-icon">⚠</span>
              API error: {apiError}
            </div>
          )}
          <ZoneVisualization
            zones={zones}
            loading={loading}
            selectedDno={selectedDno}
            onSelectZone={setSelectedDno}
          />
        </main>

        <aside className="panel panel-right">
          <RankedTable zones={zones} loading={loading} selectedDno={selectedDno} />
        </aside>
      </div>
    </div>
  )
}
