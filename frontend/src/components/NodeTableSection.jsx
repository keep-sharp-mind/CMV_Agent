import ValueRange from './ValueRange'

function NodeTableSection({
  nodeTableData,
  isLoadingNodeData,
  selectedGraphNode,
  showCode,
  nodeCode,
  isLoadingNodeCode,
  onToggleCode,
  dataResult
}) {
  if (selectedGraphNode.type !== 'd' && selectedGraphNode.type !== 'D') return null

  const processedInfo = dataResult?.processed_nodes?.[selectedGraphNode.id]

  return (
    <div className="data-table-container">
      {isLoadingNodeData ? (
        <div className="loading">Loading table data...</div>
      ) : nodeTableData ? (
        <>
          <div className="table-name-header">
            <strong>Table: </strong>
            <code>{selectedGraphNode.id}.csv</code>
            {processedInfo && (
              <span className="table-meta-badge">
                {processedInfo.row_count ?? nodeTableData.row_count} rows · {nodeTableData.columns.length} cols
              </span>
            )}
          </div>

          {nodeTableData.columns && nodeTableData.columns.length > 0 && (
            <div className="node-columns-list">
              {nodeTableData.columns.map(col => (
                <div key={col.column_name} className="column-item">
                  <span className="column-name">
                    {col.column_name}
                    {col.is_primary_key && <span className="pk-badge">PK</span>}
                  </span>
                  <span className="column-type">{col.data_type}</span>
                  {col.is_nullable && <span className="nullable-badge">nullable</span>}
                  <ValueRange valueRange={col.value_range} dataType={col.data_type} />
                </div>
              ))}
            </div>
          )}

          <div className="data-table-wrapper">
            <table className="data-table">
              <thead>
                <tr>
                  {nodeTableData.columns.map(col => (
                    <th key={col.column_name}>{col.column_name}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {nodeTableData.rows.map((row, i) => (
                  <tr key={i}>
                    {nodeTableData.columns.map(col => (
                      <td key={col.column_name}>{row[col.column_name] ?? ''}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {selectedGraphNode.type === 'D' && (
            <div style={{ marginTop: '12px' }}>
              <button
                className="expand-code-button"
                onClick={onToggleCode}
                disabled={isLoadingNodeCode}
              >
                {isLoadingNodeCode ? 'Loading...' : showCode ? 'Hide Python Code' : 'Show Python Code'}
              </button>
              {showCode && (
                <div className="code-display" style={{ marginTop: '8px' }}>
                  <pre><code>{nodeCode || 'Loading code...'}</code></pre>
                </div>
              )}
            </div>
          )}
        </>
      ) : (
        <div className="empty-table">
          {selectedGraphNode.type === 'D' && !processedInfo ? (
            'Click "Generate" to process this node'
          ) : selectedGraphNode.type === 'D' && processedInfo && !processedInfo.success ? (
            <div className="node-error-info">
              <strong>{selectedGraphNode.id} processing failed:</strong>
              {processedInfo.error && <div className="node-error-detail">{processedInfo.error}</div>}
              {processedInfo.syntax_check && !processedInfo.syntax_check.valid && (
                <div className="node-error-detail">Syntax: {processedInfo.syntax_check.error}</div>
              )}
              {processedInfo.validation_issues && processedInfo.validation_issues.length > 0 && (
                <div className="node-error-detail">
                  Validation: {processedInfo.validation_issues.map(i => i.detail).join('; ')}
                </div>
              )}
            </div>
          ) : (
            'No table data available'
          )}
        </div>
      )}
    </div>
  )
}

export default NodeTableSection