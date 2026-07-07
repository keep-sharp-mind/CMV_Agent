const AGENT_META = {
  plan: {
    name: 'Plan Agent',
    color: '#6366f1',
    icon: '📋',
    shape: 'rect',
    desc: 'Analyzes requirements and designs the analysis plan'
  },
  data: {
    name: 'Data Agent',
    color: '#f59e0b',
    icon: '⚙️',
    shape: 'hexagon',
    desc: 'Processes data through D-nodes in dependency order'
  },
  vis: {
    name: 'Vis Agent',
    color: '#10b981',
    icon: '📊',
    shape: 'circle',
    desc: 'Generates Vega-Lite visualizations for V-nodes'
  },
  interaction: {
    name: 'Interaction Agent',
    color: '#8b5cf6',
    icon: '🔄',
    shape: 'diamond',
    desc: 'Generates interaction specs for I-nodes'
  },
  error: {
    name: 'Error Agent',
    color: '#ef4444',
    icon: '⚠️',
    shape: 'diamond',
    desc: 'Handles errors and validation failures'
  }
}

const STATUS_META = {
  success: { label: 'Success', cls: 'status-success' },
  error: { label: 'Error', cls: 'status-error' },
  processing: { label: 'Processing...', cls: 'status-processing' },
  pending: { label: 'Pending', cls: 'status-pending' }
}

const MAIN_AGENTS = ['plan', 'data', 'vis', 'interaction', 'error']

function AgentShape({ type, color, active, icon }) {
  const size = 80
  const cx = 40, cy = 40

  const renderShape = () => {
    switch (type) {
      case 'rect':
        return <rect x="10" y="22" width="60" height="36" rx="10" fill={color} />
      case 'hexagon': {
        const r = 30
        const pts = []
        for (let i = 0; i < 6; i++) {
          const a = Math.PI / 6 + (Math.PI / 3) * i
          pts.push(`${cx + r * Math.cos(a)},${cy + r * Math.sin(a)}`)
        }
        return <polygon points={pts.join(' ')} fill={color} />
      }
      case 'circle':
        return <circle cx={cx} cy={cy} r="32" fill={color} />
      case 'diamond': {
        const d = 30
        return <polygon points={`${cx},${cy - d} ${cx + d * 0.7},${cy} ${cx},${cy + d} ${cx - d * 0.7},${cy}`} fill={color} />
      }
      default:
        return <circle cx={cx} cy={cy} r="32" fill={color} />
    }
  }

  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="agent-shape">
      {renderShape()}
      {active && (
        <g className="agent-flow-ring">
          {type === 'circle' ? (
            <circle cx={cx} cy={cy} r="36" fill="none" stroke={color} strokeWidth="3"
              strokeDasharray="6 4" className="flow-animation" />
          ) : type === 'rect' ? (
            <rect x="7" y="19" width="66" height="42" rx="12" fill="none" stroke={color} strokeWidth="3"
              strokeDasharray="6 4" className="flow-animation" />
          ) : type === 'hexagon' ? (
            (() => {
              const r = 34
              const pts = []
              for (let i = 0; i < 6; i++) {
                const a = Math.PI / 6 + (Math.PI / 3) * i
                pts.push(`${cx + r * Math.cos(a)},${cy + r * Math.sin(a)}`)
              }
              return <polygon points={pts.join(' ')} fill="none" stroke={color} strokeWidth="3"
                strokeDasharray="6 4" className="flow-animation" />
            })()
          ) : (
            (() => {
              const d = 34
              return <polygon points={`${cx},${cy - d} ${cx + d * 0.7},${cy} ${cx},${cy + d} ${cx - d * 0.7},${cy}`}
                fill="none" stroke={color} strokeWidth="3" strokeDasharray="6 4" className="flow-animation" />
            })()
          )}
        </g>
      )}
      <text x={cx} y={cy + 1} textAnchor="middle" dominantBaseline="central"
        fontSize="20" fill="#fff" className="agent-icon-text">
        {icon || '?'}
      </text>
    </svg>
  )
}

function AgentItem({ item, isProcessing }) {
  const status = STATUS_META[item.status] || { label: item.status || 'Pending', cls: 'status-pending' }
  return (
    <div className={`agent-item ${item.status === 'error' ? 'agent-item-error' : ''} ${isProcessing ? 'agent-item-active' : ''}`}>
      <div className="agent-item-header">
        <span className="agent-item-label">{item.label}</span>
        {isProcessing ? (
          <span className="agent-spinner" title="Processing..." />
        ) : (
          <span className={`agent-status-badge ${status.cls}`}>{status.label}</span>
        )}
      </div>
      <div className="agent-item-details">
        <div className="agent-item-io">
          <span className="io-label">Input:</span>
          <span className="io-value">{item.input || '—'}</span>
        </div>
        <div className="agent-item-io">
          <span className="io-label">Output:</span>
          <span className="io-value">{item.output || '—'}</span>
        </div>
      </div>
      {item.error_detail && (
        <div className="agent-item-error-detail">{item.error_detail}</div>
      )}
    </div>
  )
}

function buildSyntheticItems(agentId, planNodes, activeNodes) {
  if (agentId === 'plan') {
    return [
      { id: 'plan-refine', label: 'Refining requirements', status: 'success' },
      { id: 'plan-nodes', label: 'Generating nodes & dependencies', status: 'processing' }
    ]
  }

  const findCurrent = (nodeList) => {
    if (!nodeList || nodeList.length === 0) return null
    if (activeNodes && activeNodes.length > 0) {
      const found = nodeList.find(n => n.id === activeNodes[0])
      if (found) return found
    }
    return nodeList[0]
  }

  if (agentId === 'data' && planNodes?.D) {
    const curr = findCurrent(planNodes.D)
    if (!curr) return []
    return [{
      id: `data-${curr.id}`,
      label: `Process ${curr.id}${curr.name ? ': ' + curr.name : ''}`,
      status: 'processing'
    }]
  }
  if (agentId === 'vis' && planNodes?.V) {
    const curr = findCurrent(planNodes.V)
    if (!curr) return []
    return [{
      id: `vis-${curr.id}`,
      label: `Generate ${curr.id}${curr.name ? ': ' + curr.name : ''}`,
      status: 'processing'
    }]
  }
  if (agentId === 'interaction') {
    const nodes = planNodes?.I
    if (!nodes || nodes.length === 0) return []
    const curr = findCurrent(nodes)
    if (!curr) return [{
      id: 'interaction-generate',
      label: 'Generating interaction specs',
      status: 'processing'
    }]
    return [{
      id: `interaction-${curr.id}`,
      label: `Generate ${curr.id}${curr.name ? ': ' + curr.name : ''}`,
      status: 'processing'
    }]
  }
  if (agentId === 'error') {
    return [{ id: 'error-check', label: 'Checking for errors', status: 'processing' }]
  }
  return []
}

function sortItems(items) {
  const sorted = [...items]
  sorted.sort((a, b) => {
    if (a.status === 'processing' && b.status !== 'processing') return -1
    if (a.status !== 'processing' && b.status === 'processing') return 1
    return 0
  })
  return sorted
}

function summarizeItems(items) {
  const counts = items.reduce((acc, item) => {
    const key = item.status || 'pending'
    acc[key] = (acc[key] || 0) + 1
    return acc
  }, {})
  return counts
}

function getVisibleItems(items) {
  if (!items || items.length === 0) return []
  return items
}

function buildItemsFromNodeStatus(agentId, nodeList, nodeStatus) {
  const items = []
  for (const n of nodeList) {
    const statusArr = nodeStatus[n.id]
    if (!statusArr || !Array.isArray(statusArr)) continue
    for (let i = 0; i < statusArr.length; i++) {
      const entry = statusArr[i]
      const baseLabel = agentId === 'data'
        ? `Process ${n.id}${n.name ? ': ' + n.name : ''}`
        : `Generate ${n.id}${n.name ? ': ' + n.name : ''}`
      const label = entry.retryNodeId
        ? `Regenerate ${entry.retryNodeId}${n.name ? ': ' + n.name : ''}`
        : entry.attempt > 1
        ? `${baseLabel} (attempt ${entry.attempt})`
        : baseLabel
      items.push({
        id: `${agentId}-${n.id}-${i}`,
        label,
        status: entry.status,
        input: entry.input,
        output: entry.output,
        error_detail: entry.error_detail
      })
    }
  }
  return items
}

function AgentFlow({ agents, activeAgent, activeNodes, nodeStatus, expandedAgent, onToggleExpand, generating, planNodes, dependencies, errorRetryEntries }) {
  const showAll = generating || planNodes

  if (!showAll && !agents) return null

  const isExpanded = (id) => {
    if (generating) return id === activeAgent
    return expandedAgent === id
  }

  const getItems = (id) => {
    const realAgent = agents?.[id]
    if (realAgent?.items?.length > 0) {
      return sortItems(realAgent.items)
    }

    if (!generating) {
      if (id === 'error' && errorRetryEntries && errorRetryEntries.length > 0) {
        return sortItems(errorRetryEntries.map(e => ({ ...e })))
      }
      return []
    }

    if (id === 'error' && errorRetryEntries && errorRetryEntries.length > 0) {
      return sortItems(errorRetryEntries.map(e => ({ ...e })))
    }

    if (id !== activeAgent) return []

    if ((id === 'data' || id === 'vis') && nodeStatus && Object.keys(nodeStatus).length > 0) {
      const nodeList = id === 'data' ? planNodes?.D : planNodes?.V
      if (nodeList && nodeList.length > 0) {
        const items = buildItemsFromNodeStatus(id, nodeList, nodeStatus)
        if (items.length > 0) return sortItems(items)
      }
    }

    return sortItems(buildSyntheticItems(id, planNodes, activeNodes))
  }

  return (
    <div className="agent-flow-container">
      <div className="agent-flow-header">
        <h3>Agent Execution Flow</h3>
        {generating && (
          <span className="agent-flow-badge">Running...</span>
        )}
      </div>
      <div className="agent-flow-body">
        <div className="agent-nodes-row">
          {MAIN_AGENTS.map((id) => {
            const meta = AGENT_META[id] || {}
            const isActive = activeAgent === id
            const exp = isExpanded(id)
            const items = getItems(id)
            const counts = summarizeItems(items)
            const visibleItems = getVisibleItems(items)

            return (
              <div key={id} className={`agent-node-wrapper ${isActive ? 'agent-wrapper-active' : ''}`}>
                <div
                  className={`agent-node ${isActive ? 'agent-active' : ''} ${exp ? 'agent-expanded' : ''}`}
                  onClick={() => onToggleExpand && onToggleExpand(id)}
                >
                  <AgentShape type={meta.shape || 'circle'} color={meta.color} active={isActive} icon={meta.icon} />
                  <div className="agent-name" style={{ color: meta.color }}>
                    {meta.name}
                  </div>
                  {isActive && generating && (
                    <div className="agent-status-label">{meta.desc}</div>
                  )}
                  {items.length > 0 && (
                    <div className="agent-summary-pills">
                      {counts.success > 0 && <span className="agent-summary-pill summary-success">{counts.success}</span>}
                      {counts.error > 0 && <span className="agent-summary-pill summary-error">{counts.error}</span>}
                      {counts.processing > 0 && <span className="agent-summary-pill summary-processing">{counts.processing}</span>}
                    </div>
                  )}
                </div>

                {/* Detail panel */}
                {(exp || isActive) && visibleItems.length > 0 && (
                  <div className="agent-detail-panel">
                    {visibleItems.map(item => (
                      <AgentItem key={item.id} item={item} isProcessing={item.status === 'processing'} />
                    ))}
                  </div>
                )}
                {exp && visibleItems.length === 0 && (
                  <div className="agent-detail-panel agent-detail-empty">
                    {generating ? 'Waiting for tasks...' : 'No items yet'}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

export default AgentFlow
