import { useState } from 'react'

const BACKEND = ''  // proxied via Vite to localhost:8080

type Mode = 'ask' | 'chart'

interface AskResult {
  answer: Record<string, unknown>[]
  sql: string
}

interface ChartResult {
  embed_url: string
  sql: string
}

export default function App() {
  const [mode, setMode] = useState<Mode>('ask')
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [askResult, setAskResult] = useState<AskResult | null>(null)
  const [chartResult, setChartResult] = useState<ChartResult | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function submit() {
    if (!input.trim()) return
    setLoading(true)
    setError(null)
    setAskResult(null)
    setChartResult(null)

    try {
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
          {(['ask', 'chart'] as Mode[]).map((m) => (
            <button
              key={m}
              style={{ ...styles.tab, ...(mode === m ? styles.tabActive : {}) }}
              onClick={() => { setMode(m); setAskResult(null); setChartResult(null); setError(null) }}
            >
              {m === 'ask' ? 'Ask a Question' : 'Generate Chart'}
            </button>
          ))}
        </div>

        {/* Input */}
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
