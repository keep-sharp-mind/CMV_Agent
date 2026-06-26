function VisSection({
  visSpec,
  showVisCode,
  onToggleVisCode,
  chartContainerRef
}) {
  if (!visSpec) {
    return (
      <div className="empty-table">
        No visualization generated. Click "Process Data" to generate.
      </div>
    )
  }

  const metadata = visSpec.metadata || {}
  const spec = visSpec.spec || {}

  const extractSpecEncoding = () => {
    if (!spec || !spec.encoding) return null
    return Object.entries(spec.encoding).map(([channel, enc]) => {
      const field = enc.field || enc.fieldName || '?'
      const etype = enc.type || ''
      const agg = enc.aggregate || ''
      return { channel, field, type: etype, aggregate: agg }
    })
  }

  const specEncodings = extractSpecEncoding()

  return (
    <div className="vis-container">
      {visSpec.spec && (
        <div className="chart-wrapper" ref={chartContainerRef}></div>
      )}
      {!visSpec.success && visSpec.error && (
        <div className="vis-error">
          Validation: {visSpec.error}
        </div>
      )}
      {visSpec.validation_issues && visSpec.validation_issues.length > 0 && (
        <div className="vis-validation-issues">
          {visSpec.validation_issues.map((issue, i) => (
            <div key={i} className="vis-issue-item">{issue.type}: {issue.detail}</div>
          ))}
        </div>
      )}

      <div className="vis-metadata">
        <span className="vis-metadata-item">
          <strong>Mark:</strong> {metadata.marktype || spec.mark || 'N/A'}
        </span>
        {metadata.used_tables && metadata.used_tables.length > 0 && (
          <span className="vis-metadata-item">
            <strong>Data Tables:</strong> {metadata.used_tables.join(', ')}
          </span>
        )}
        {metadata.used_fields && metadata.used_fields.length > 0 && (
          <span className="vis-metadata-item">
            <strong>Used Fields:</strong> {metadata.used_fields.join(', ')}
          </span>
        )}
      </div>

      {specEncodings && specEncodings.length > 0 && (
        <div className="vis-encoding-table">
          <strong>Encoding Channels</strong>
          <table>
            <thead>
              <tr>
                <th>Channel</th>
                <th>Field</th>
                <th>Type</th>
                <th>Aggregate</th>
              </tr>
            </thead>
            <tbody>
              {specEncodings.map((enc, i) => (
                <tr key={i}>
                  <td><code>{enc.channel}</code></td>
                  <td><code>{enc.field}</code></td>
                  <td>{enc.type}</td>
                  <td>{enc.aggregate || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {visSpec.spec_json && (
        <div style={{ marginTop: '8px' }}>
          <button
            className="expand-code-button"
            onClick={onToggleVisCode}
          >
            {showVisCode ? 'Hide Vega-Lite Code' : 'Show Vega-Lite Code'}
          </button>
          {showVisCode && (
            <div className="code-display" style={{ marginTop: '8px' }}>
              <pre><code>{visSpec.spec_json}</code></pre>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default VisSection