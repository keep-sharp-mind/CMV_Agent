function DataFlowTable({ nodeDataFlow, planNodes }) {
  if (!nodeDataFlow || Object.keys(nodeDataFlow).length === 0) return null

  const nodeLabel = (id) => {
    if (!planNodes) return id
    for (const type of ['d', 'D', 'V', 'I']) {
      const found = planNodes[type]?.find(n => n.id === id)
      if (found) return found.label || id
    }
    return id
  }

  const renderTags = (fields, className, emptyLabel = '—') => {
    return fields?.length > 0
      ? fields.map((field, index) => (
          <span key={`${className}-${index}`} className={`data-flow-tag ${className}`}>
            {field}
          </span>
        ))
      : <span className={`data-flow-tag ${className}`} style={{ opacity: 0.4 }}>{emptyLabel}</span>
  }

  const renderPredictedTags = (fields) => {
    return fields?.map((field, index) => (
      <span
        key={`predicted-${index}`}
        className="data-flow-tag predicted"
        title="Predicted shared-field fallback; not yet confirmed by generated code/spec"
      >
        {field}
      </span>
    ))
  }

  const allNodes = Object.entries(nodeDataFlow).sort(([a], [b]) => a.localeCompare(b))

  return (
    <div className="plan-subsection">
      <h3>Data Flow Table</h3>
      <div className="data-flow-legend">
        <span className="data-flow-tag predicted">predicted</span>
        <span className="data-flow-legend-text">Predicted shared fields are suggestions only; confirmed fields use normal colors.</span>
      </div>
      <div className="data-flow-table-wrap">
        <table className="data-flow-table">
          <thead>
            <tr>
              <th>Node</th>
              <th>In Fields</th>
              <th>Out Fields</th>
            </tr>
          </thead>
          <tbody>
            {allNodes.map(([nodeId, flow]) => (
              <tr key={nodeId}>
                <td className="data-flow-node-id">{nodeLabel(nodeId)}</td>
                <td>
                  {renderTags(flow.in_fields, 'in')}
                  {renderPredictedTags(flow.predicted_in_fields)}
                </td>
                <td>
                  {renderTags(flow.out_fields, 'out')}
                  {renderPredictedTags(flow.predicted_out_fields)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

export default DataFlowTable
