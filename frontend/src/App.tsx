import { useState } from 'react'

const BACKEND = ''  // proxied via Vite to localhost:8080

type Mode = 'ask' | 'chart' | 'points'

interface AskResult {
  answer: Record<string, unknown>[]
  sql: string
}

interface ChartResult {
  embed_url: string
  sql: string
}

interface PointsBreakdownRow {
  team_name: string
  team_colour: string | null
  team_points: number
  efficiency_pct: number
}

interface PointsResult {
  embed_url: string
  sql: string
  breakdown: PointsBreakdownRow[]
}

export default function App() {
  const [mode, setMode] = useState<Mode>('ask')
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [askResult, setAskResult] = useState<AskResult | null>(null)
  const [chartResult, setChartResult] = useState<ChartResult | null>(null)
  const [pointsResult, setPointsResult] = useState<PointsResult | null>(null)
  const [error, setError] = useState<string | null>(null)

  // Points mode uses separate inputs
  const [pointsCircuit, setPointsCircuit] = useState('')
  const [pointsYear, setPointsYear] = useState(2026)

  function clearResults() {
    setAskResult(null)
    setChartResult(null)
    setPointsResult(null)
    setError(null)
  }

  async function submit() {
    if (mode !== 'points' && !input.trim()) return
    setLoading(true)
    setError(null)
    setAskResult(null)
    setChartResult(null)
    setPointsResult(null)

    try {
      if (mode === 'points') {
        const body: Record<string, unknown> = { year: pointsYear }
        if (pointsCircuit.trim()) body.circuit = pointsCircuit.trim()
        const resp = await fetch(`${BACKEND}/api/points-chart`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        })
        if (!resp.ok) {
          const err = await resp.json().catch(() => ({}))
          throw new Error(err.detail ?? `HTTP ${resp.status}`)
        }
        setPointsResult(await resp.json())
      } else {
        const endpoint = mode === 'ask' ? '/api/ask' : '/api/chart'
        const body = mode === 'ask' ? { question: input } : { prompt: input }
        const resp = await fetch(`${BACKEND}${endpoint}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        })
        if (!resp.ok) {
          const err = await resp.json().catch(() => ({}))
          throw new Error(err.detail ?? `HTTP ${resp.status}`)
        }
        const data = await resp.json()
        if (mode === 'ask') setAskResult(data)
        else setChartResult(data)
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={styles.page}>
      <header style={styles.header}>
        <h1 style={styles.title}>F1 Analytics</h1>
        <p style={styles.subtitle}>Natural language queries and charts over live Formula 1 data</p>
      </header>

      <main style={styles.main}>
        {/* Mode toggle */}
        <div style={styles.tabs}>
          {(['ask', 'chart', 'points'] as Mode[]).map((m) => (
            <button
              key={m}
              style={{ ...styles.tab, ...(mode === m ? styles.tabActive : {}) }}
              onClick={() => { setMode(m); clearResults() }}
            >
              {m === 'ask' ? 'Ask a Question' : m === 'chart' ? 'Generate Chart' : 'Points %'}
            </button>
          ))}
        </div>

        {/* Input — ask/chart modes */}
        {mode !== 'points' && (
          <div style={styles.inputRow}>
            <input
              style={styles.input}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && submit()}
              placeholder={
                mode === 'ask'
                  ? 'Who had the top speed at Suzuka in 2026?'
                  : 'Top 10 lap times at Suzuka, fastest first'
              }
              disabled={loading}
            />
            <button style={styles.button} onClick={submit} disabled={loading}>
              {loading ? '...' : mode === 'ask' ? 'Ask' : 'Chart'}
            </button>
          </div>
        )}

        {/* Input — points mode */}
        {mode === 'points' && (
          <div style={styles.inputRow}>
            <input
              style={{ ...styles.input, flex: 2 }}
              value={pointsCircuit}
              onChange={(e) => setPointsCircuit(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && submit()}
              placeholder="Circuit name (e.g. Suzuka) — leave blank for full season"
              disabled={loading}
            />
            <input
              style={{ ...styles.input, flex: '0 0 90px', textAlign: 'center' }}
              type="number"
              value={pointsYear}
              onChange={(e) => setPointsYear(Number(e.target.value))}
              onKeyDown={(e) => e.key === 'Enter' && submit()}
              disabled={loading}
            />
            <button style={styles.button} onClick={submit} disabled={loading}>
              {loading ? '...' : 'Show'}
            </button>
          </div>
        )}

        {/* Error */}
        {error && <div style={styles.error}>{error}</div>}

        {/* Ask result */}
        {askResult && (
          <div style={styles.resultBox}>
            <ResultTable rows={askResult.answer} />
            <details style={styles.sqlDetails}>
              <summary>Generated SQL</summary>
              <pre style={styles.sql}>{askResult.sql}</pre>
            </details>
          </div>
        )}

        {/* Chart result */}
        {chartResult && (
          <div style={styles.resultBox}>
            <iframe
              src={chartResult.embed_url}
              style={styles.iframe}
              title="Metabase Chart"
            />
            <details style={styles.sqlDetails}>
              <summary>Generated SQL</summary>
              <pre style={styles.sql}>{chartResult.sql}</pre>
            </details>
          </div>
        )}

        {/* Points result */}
        {pointsResult && (
          <div style={styles.resultBox}>
            <iframe
              src={pointsResult.embed_url}
              style={styles.iframe}
              title="Points Efficiency Chart"
            />
            <BreakdownTable rows={pointsResult.breakdown} />
            <details style={styles.sqlDetails}>
              <summary>SQL</summary>
              <pre style={styles.sql}>{pointsResult.sql}</pre>
            </details>
          </div>
        )}
      </main>
    </div>
  )
}

function ResultTable({ rows }: { rows: Record<string, unknown>[] }) {
  if (!rows?.length) return <p style={{ color: '#888' }}>No results.</p>
  const cols = Object.keys(rows[0])
  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={styles.table}>
        <thead>
          <tr>
            {cols.map((c) => <th key={c} style={styles.th}>{c}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i}>
              {cols.map((c) => <td key={c} style={styles.td}>{String(row[c] ?? '')}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function BreakdownTable({ rows }: { rows: PointsBreakdownRow[] }) {
  if (!rows?.length) return null
  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={styles.table}>
        <thead>
          <tr>
            <th style={styles.th}>Team</th>
            <th style={{ ...styles.th, textAlign: 'right' }}>Points</th>
            <th style={{ ...styles.th, textAlign: 'right' }}>Efficiency %</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.team_name}>
              <td style={styles.td}>
                {row.team_colour && (
                  <span style={{
                    display: 'inline-block',
                    width: 12,
                    height: 12,
                    borderRadius: 2,
                    background: row.team_colour,
                    marginRight: 8,
                    verticalAlign: 'middle',
                  }} />
                )}
                {row.team_name}
              </td>
              <td style={{ ...styles.td, textAlign: 'right' }}>{row.team_points}</td>
              <td style={{ ...styles.td, textAlign: 'right' }}>{row.efficiency_pct.toFixed(2)}%</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

const styles: Record<string, React.CSSProperties> = {
  page: { maxWidth: 900, margin: '0 auto', padding: '24px 16px' },
  header: { marginBottom: 32 },
  title: { fontSize: 28, fontWeight: 700, color: '#e10600' },
  subtitle: { color: '#888', marginTop: 4 },
  main: { display: 'flex', flexDirection: 'column', gap: 16 },
  tabs: { display: 'flex', gap: 8 },
  tab: { padding: '8px 20px', borderRadius: 6, border: '1px solid #333', background: 'transparent', color: '#aaa', cursor: 'pointer', fontSize: 14 },
  tabActive: { background: '#e10600', color: '#fff', borderColor: '#e10600' },
  inputRow: { display: 'flex', gap: 8 },
  input: { flex: 1, padding: '10px 14px', borderRadius: 6, border: '1px solid #333', background: '#1a1a1a', color: '#f0f0f0', fontSize: 15 },
  button: { padding: '10px 20px', borderRadius: 6, border: 'none', background: '#e10600', color: '#fff', fontWeight: 600, cursor: 'pointer', fontSize: 15 },
  error: { padding: 12, borderRadius: 6, background: '#2a1010', color: '#ff6b6b', fontSize: 14 },
  resultBox: { display: 'flex', flexDirection: 'column', gap: 12 },
  table: { width: '100%', borderCollapse: 'collapse', fontSize: 14 },
  th: { padding: '8px 12px', textAlign: 'left', borderBottom: '1px solid #333', color: '#aaa', fontWeight: 600 },
  td: { padding: '8px 12px', borderBottom: '1px solid #1e1e1e' },
  iframe: { width: '100%', height: 480, border: 'none', borderRadius: 8 },
  sqlDetails: { fontSize: 13, color: '#666' },
  sql: { marginTop: 8, padding: 12, background: '#1a1a1a', borderRadius: 6, overflowX: 'auto', fontSize: 12, color: '#aaa' },
}
