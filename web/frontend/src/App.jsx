import { useState, useRef } from 'react'

const API_BASE = 'http://localhost:8000'

// Simple state machine: idle -> loading -> (clarifying | done | error)
export default function App() {
  const [question, setQuestion] = useState('')
  const [useClarification, setUseClarification] = useState(true)
  const [phase, setPhase] = useState('idle') // idle | loading | clarifying | done | error
  const [clarification, setClarification] = useState(null) // { question, reason }
  const [answer, setAnswer] = useState('')
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')

  // Dataset upload state -- null session means "using bundled sample data"
  const [sessionId, setSessionId] = useState(null)
  const [datasetTables, setDatasetTables] = useState(null)
  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState('')
  const fileInputRef = useRef(null)

  async function handleFileUpload(e) {
    const files = Array.from(e.target.files || [])
    if (files.length === 0) return
    setUploading(true)
    setUploadError('')

    try {
      const formData = new FormData()
      files.forEach((f) => formData.append('files', f))
      const res = await fetch(`${API_BASE}/api/upload`, { method: 'POST', body: formData })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || 'Upload failed')

      setSessionId(data.session_id)
      setDatasetTables(data.tables)
      reset() // clear any previous question/result, start fresh on the new dataset
    } catch (err) {
      setUploadError(err.message)
    } finally {
      setUploading(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  function useSampleData() {
    setSessionId(null)
    setDatasetTables(null)
    setUploadError('')
    reset()
  }

  async function submitQuestion(e) {
    e.preventDefault()
    if (!question.trim()) return
    setPhase('loading')
    setError('')
    setResult(null)
    setClarification(null)

    try {
      const res = await fetch(`${API_BASE}/api/ask`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question, use_clarification: useClarification, session_id: sessionId }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || 'Request failed')

      if (data.status === 'clarification_needed') {
        setClarification({ question: data.clarification_question, reason: data.ambiguity_reason })
        setPhase('clarifying')
      } else {
        setResult(data)
        setPhase('done')
      }
    } catch (err) {
      setError(err.message)
      setPhase('error')
    }
  }

  async function submitAnswer(e) {
    e.preventDefault()
    if (!answer.trim()) return
    setPhase('loading')
    setError('')

    try {
      const res = await fetch(`${API_BASE}/api/resolve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          question,
          clarification_question: clarification.question,
          answer,
          session_id: sessionId,
        }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || 'Request failed')
      setResult(data)
      setPhase('done')
    } catch (err) {
      setError(err.message)
      setPhase('error')
    }
  }

  function reset() {
    setQuestion('')
    setAnswer('')
    setClarification(null)
    setResult(null)
    setError('')
    setPhase('idle')
  }

  return (
    <div className="container">
      <h1>ClarifySQL</h1>
      <p className="subtitle">
        Ask a question in plain English. If it's genuinely ambiguous given the schema,
        you'll be asked to clarify before SQL is generated.
      </p>

      <div className="dataset-box">
        <div className="dataset-header">
          <span className="dataset-label">Dataset</span>
          {sessionId ? (
            <button type="button" className="link-button" onClick={useSampleData}>
              switch back to sample data
            </button>
          ) : (
            <span className="dataset-current">using bundled sample data</span>
          )}
        </div>

        {datasetTables && (
          <div className="dataset-tables">
            {datasetTables.map((t) => (
              <span key={t.name} className="table-chip">
                {t.name} ({t.row_count} rows)
              </span>
            ))}
          </div>
        )}

        <label className="upload-label">
          <input
            ref={fileInputRef}
            type="file"
            accept=".csv,.xlsx,.xls,.db,.sqlite,.sqlite3"
            multiple
            onChange={handleFileUpload}
            disabled={uploading}
          />
          {uploading ? 'Uploading...' : 'Upload your own CSV / Excel / SQLite file(s)'}
        </label>
        {uploadError && <div className="upload-error">{uploadError}</div>}
      </div>

      <form onSubmit={submitQuestion} className="ask-form">
        <textarea
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="e.g. What's the total amount for order 10?"
          rows={2}
          disabled={phase === 'loading' || phase === 'clarifying'}
        />
        <div className="form-row">
          <label>
            <input
              type="checkbox"
              checked={useClarification}
              onChange={(e) => setUseClarification(e.target.checked)}
              disabled={phase === 'loading' || phase === 'clarifying'}
            />
            Clarification enabled
          </label>
          <button type="submit" disabled={phase === 'loading' || phase === 'clarifying'}>
            {phase === 'loading' ? 'Working...' : 'Ask'}
          </button>
          {(result || error) && (
            <button type="button" className="secondary" onClick={reset}>
              New question
            </button>
          )}
        </div>
      </form>

      {phase === 'clarifying' && clarification && (
        <form onSubmit={submitAnswer} className="clarify-box">
          <div className="clarify-label">Clarifying question</div>
          <div className="clarify-question">{clarification.question}</div>
          <input
            type="text"
            value={answer}
            onChange={(e) => setAnswer(e.target.value)}
            placeholder="Your answer..."
            autoFocus
          />
          <button type="submit">Continue</button>
        </form>
      )}

      {error && (
        <div className="error-box">
          <strong>Error:</strong> {error}
        </div>
      )}

      {result && result.status === 'done' && (
        <div className="result">
          {result.clarification_used && (
            <div className="badge">Resolved via clarification: "{result.resolved_question}"</div>
          )}
          <div className="sql-label">Generated SQL</div>
          <pre className="sql-block">{result.sql}</pre>
          {result.assumptions && (
            <div className="assumptions">Assumption: {result.assumptions}</div>
          )}

          <div className="sql-label">Results ({result.rows.length} rows)</div>
          {result.rows.length === 0 ? (
            <div className="no-rows">No rows returned.</div>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    {result.columns.map((c) => (
                      <th key={c}>{c}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {result.rows.map((row, i) => (
                    <tr key={i}>
                      {row.map((cell, j) => (
                        <td key={j}>{String(cell)}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
