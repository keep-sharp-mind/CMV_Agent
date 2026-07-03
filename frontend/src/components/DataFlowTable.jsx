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

  const allNodes = Object.entries(nodeDataFlow).sort(([a], [b]) => a.localeCompare(b))

  return (
    <div className="plan-subsection">
      <h3>Data Flow Table</h3>
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
                  {flow.in_fields?.length > 0
                    ? flow.in_fields.map((f, i) => (
                        <span key={i} className="data-flow-tag in">{f}</span>
                      ))
                    : <span className="data-flow-tag in" style={{opacity:0.4}}>—</span>}
                </td>
                <td>
                  {flow.out_fields?.length > 0
                    ? flow.out_fields.map((f, i) => (
                        <span key={i} className="data-flow-tag out">{f}</span>
                      ))
                    : <span className="data-flow-tag out" style={{opacity:0.4}}>—</span>}
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
