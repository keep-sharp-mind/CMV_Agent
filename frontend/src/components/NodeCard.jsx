function NodeCard({ node, type }) {
  return (
    <div className={`node-card ${type}-node`}>
      <div className="node-id">{node.id}</div>
      <div className="node-name">{node.name}</div>
      <div className="node-desc">{node.description}</div>
      {type === 'd' && node.source_table && (
        <div className="node-meta">source: {node.source_table}</div>
      )}
      {type === 'D' && node.task && (
        <div className="node-task">
          <div className="node-task-label">Task:</div>
          <div className="node-task-content">{node.task}</div>
        </div>
      )}
      {type === 'V' && node.chart_type && (
        <div className="node-meta">chart: {node.chart_type}</div>
      )}
      {type === 'I' && (
        <div className="node-meta">
          trigger: {node.trigger} | effect: {node.effect}
        </div>
      )}
    </div>
  )
}

export default NodeCard
