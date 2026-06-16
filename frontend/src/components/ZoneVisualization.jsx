import { useState, useEffect, useRef } from 'react'
import './ZoneVisualization.css'

/* ── Colour helpers ─────────────────────────────────────────────────────────── */

function scoreToColor(score) {
  const s = Math.max(0, Math.min(1, score ?? 0))
  // #E8F5E9 (pale, score=0) → #1B5E20 (dark, score=1)
  const r = Math.round(232 + (27  - 232) * s)
  const g = Math.round(245 + (94  - 245) * s)
  const b = Math.round(233 + (32  - 233) * s)
  return `rgb(${r},${g},${b})`
}

function textForScore(score) {
  return score > 0.52 ? '#fff' : '#1A1A1A'
}

/* ── Bar Chart (primary / fallback view) ────────────────────────────────────── */

function SkeletonBars() {
  return (
    <div className="bar-chart-wrap">
      {Array.from({ length: 14 }, (_, i) => (
        <div key={i} className="bar-row skeleton-row">
          <div className="bar-meta">
            <span className="bar-rank skeleton-block" style={{ width: 20, height: 20, borderRadius: '50%' }} />
            <span className="bar-name skeleton-block" style={{ width: 140 + (i % 3) * 20 }} />
          </div>
          <div className="bar-track">
            <div className="bar-fill skeleton-block" style={{ width: `${30 + Math.random() * 50}%` }} />
          </div>
          <span className="bar-score skeleton-block" style={{ width: 38 }} />
        </div>
      ))}
    </div>
  )
}

function BarChart({ zones }) {
  if (!zones.length) return <SkeletonBars />

  // zones arrive pre-sorted by rank (rank 1 = highest composite)
  const topScore = zones[0]?.composite ?? 1

  return (
    <div className="bar-chart-wrap">
      {zones.map(zone => {
        const color = scoreToColor(zone.composite)
        const pct   = (zone.composite / Math.max(topScore, 0.001)) * 100

        return (
          <div key={zone.dno} className="bar-row">
            <div className="bar-meta">
              <span className={`bar-rank${zone.rank <= 3 ? ' bar-rank-top' : ''}`}>
                {zone.rank}
              </span>
              <span className="bar-name" title={zone.dno}>{zone.dno}</span>
            </div>

            <div className="bar-track">
              <div
                className="bar-fill"
                style={{ width: `${pct}%`, background: color }}
              >
                <span
                  className="bar-score-inside"
                  style={{ color: textForScore(zone.composite) }}
                >
                  {zone.composite.toFixed(3)}
                </span>
              </div>
            </div>

            {zone.d4_pending && (
              <span className="pending-tag" title="D4 score pending — Scotland/Wales deprivation data not yet harmonised">
                D4⚠
              </span>
            )}
          </div>
        )
      })}
    </div>
  )
}

/* ── Leaflet Map (activates if /dno-boundaries.geojson loads) ───────────────── */

const DIM_KEYS = ['d1', 'd2', 'd3', 'd4', 'd5']

function tooltipHtml(zone) {
  if (!zone) return ''
  const dims = DIM_KEYS
    .map(k => `<span>${k.toUpperCase()} ${(zone.scores[k] ?? 0).toFixed(2)}${
      k === 'd4' && zone.d4_pending ? '⚠' : ''
    }</span>`)
    .join('')
  return `
    <div class="map-tooltip">
      <strong>${zone.dno}</strong>
      <div class="map-tooltip-score">Score <b>${zone.composite.toFixed(3)}</b> · Rank ${zone.rank} / 14</div>
      <div class="map-tooltip-dims">${dims}</div>
    </div>`
}

function LeafletMap({ zones, geoJson, selectedDno, onSelectZone }) {
  const containerRef  = useRef(null)
  const mapRef        = useRef(null)
  const layerRef       = useRef(null)
  const layersByDno    = useRef({})
  const zonesRef        = useRef(zones)
  const selectedRef      = useRef(selectedDno)
  const [mapReady, setMapReady] = useState(false)
  zonesRef.current = zones
  selectedRef.current = selectedDno

  // Repaint one polygon's fill colour, border (selection highlight) and tooltip
  // from the *current* zone data — called both on initial build and on every
  // weight-driven score update, without rebuilding the GeoJSON layer.
  function paintLayer(name, layer) {
    const zone = zonesRef.current.find(z => z.dno === name)
    const isSelected = name === selectedRef.current
    layer.setStyle({
      fillColor:   scoreToColor(zone?.composite ?? 0),
      weight:      isSelected ? 3 : 1.5,
      color:       isSelected ? '#F57F17' : '#fff',
      fillOpacity: 0.82,
    })
    layer.setTooltipContent(tooltipHtml(zone))
    if (isSelected) layer.bringToFront()
  }

  function paintAll() {
    Object.entries(layersByDno.current).forEach(([name, layer]) => paintLayer(name, layer))
  }

  // Initialise map once: minimal CartoDB Positron basemap, centred on GB.
  // `cancelled` guards against React StrictMode's dev-only double-mount,
  // which would otherwise call L.map() twice on the same DOM node.
  useEffect(() => {
    if (!containerRef.current) return
    let cancelled = false

    import('leaflet').then(mod => {
      if (cancelled || mapRef.current) return
      const L = mod.default
      const map = L.map(containerRef.current, {
        center: [54.5, -2.5],
        zoom: 6,
        minZoom: 5,
        maxZoom: 9,
      })
      mapRef.current = map

      L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
        attribution: '© <a href="https://openstreetmap.org">OpenStreetMap</a> contributors © <a href="https://carto.com/attributions">CARTO</a>',
        subdomains: 'abcd',
        maxZoom: 19,
      }).addTo(map)

      setMapReady(true)
    })

    return () => {
      cancelled = true
      if (mapRef.current) {
        mapRef.current.remove()
        mapRef.current = null
        setMapReady(false)
      }
    }
  }, [])

  // Build the GeoJSON layer once the map exists AND the boundary file is
  // loaded. Each feature was pre-tagged with a `dno_zone` property (during
  // data prep) matching the canonical names used everywhere else in the app.
  useEffect(() => {
    if (!mapRef.current || !geoJson) return

    // eslint-disable-next-line no-console
    console.log(
      '[DNO boundary map] feature properties:',
      geoJson.features.map(f => f.properties)
    )

    import('leaflet').then(mod => {
      const L = mod.default
      if (layerRef.current) { layerRef.current.remove(); layerRef.current = null }
      layersByDno.current = {}

      layerRef.current = L.geoJSON(geoJson, {
        style: () => ({ fillColor: '#E8F5E9', weight: 1.5, color: '#fff', fillOpacity: 0.82 }),
        onEachFeature: (feature, layer) => {
          const name = feature.properties?.dno_zone
            || feature.properties?.DNO_NAME
            || feature.properties?.Name
            || feature.properties?.name
            || ''
          if (!name) return
          layersByDno.current[name] = layer

          layer.bindTooltip('', { direction: 'top', sticky: true, className: 'leaflet-tooltip-clean' })
          layer.on('mouseover', () => layer.setStyle({ weight: 3, color: '#1B5E20' }))
          layer.on('mouseout',  () => paintLayer(name, layer))
          layer.on('click',     () => onSelectZone?.(name))
        },
      }).addTo(mapRef.current)

      paintAll()
    })
  }, [geoJson, mapReady]) // eslint-disable-line react-hooks/exhaustive-deps

  // Recolour / re-tooltip / re-highlight every polygon whenever the composite
  // scores change (weight sliders moved) or the selected zone changes.
  useEffect(() => {
    paintAll()
  }, [zones, selectedDno])

  return <div ref={containerRef} className="leaflet-map" />
}

/* ── Main export ────────────────────────────────────────────────────────────── */

export default function ZoneVisualization({ zones, loading, selectedDno, onSelectZone }) {
  const [geoJson, setGeoJson]     = useState(null)  // null = loading, false = failed
  const [mapReady, setMapReady]   = useState(false)
  const [view, setView]           = useState('map')  // user's preferred view: 'map' | 'bars'

  // Try to load DNO boundary GeoJSON once
  useEffect(() => {
    // Dynamically import leaflet CSS only when map might be used
    import('leaflet/dist/leaflet.css').catch(() => {})

    fetch('/dno-boundaries.geojson')
      .then(r => { if (!r.ok) throw new Error('Not found'); return r.json() })
      .then(data => { setGeoJson(data); setMapReady(true) })
      .catch(() => { setGeoJson(false) })
  }, [])

  const mapAvailable = mapReady && !!geoJson
  const showMap = mapAvailable && view === 'map'

  return (
    <div className="viz-root">
      <div className="viz-header">
        <div className="viz-title-group">
          <h2 className="viz-title">
            {showMap ? 'DNO Zone Map' : 'Composite Score by Zone'}
          </h2>
          <span className="viz-subtitle">
            {showMap
              ? 'Darker green = higher composite score'
              : 'Ranked by current weight settings · sorted highest first'}
          </span>
        </div>
        <div className="viz-header-right">
          {loading && <span className="updating-chip">Updating…</span>}
          {mapAvailable && (
            <div className="view-toggle" role="group" aria-label="Visualisation view">
              <button
                type="button"
                className={`view-toggle-btn${view === 'map' ? ' active' : ''}`}
                onClick={() => setView('map')}
              >
                Map
              </button>
              <button
                type="button"
                className={`view-toggle-btn${view === 'bars' ? ' active' : ''}`}
                onClick={() => setView('bars')}
              >
                Bars
              </button>
            </div>
          )}
          {!mapAvailable && geoJson === false && (
            <span
              className="map-unavail-chip"
              title="Add dno-boundaries.geojson to frontend/public/ to enable the map view"
            >
              Map: add GeoJSON to enable
            </span>
          )}
        </div>
      </div>

      <div className="viz-body">
        {showMap
          ? <LeafletMap
              zones={zones}
              geoJson={geoJson}
              selectedDno={selectedDno}
              onSelectZone={onSelectZone}
            />
          : <BarChart zones={zones} />
        }
      </div>

      <div className="viz-legend">
        <div className="legend-label">Score</div>
        <div className="legend-gradient" />
        <div className="legend-ticks">
          {[0, 0.25, 0.5, 0.75, 1].map(v => (
            <span key={v}>{v.toFixed(2)}</span>
          ))}
        </div>
      </div>
    </div>
  )
}
