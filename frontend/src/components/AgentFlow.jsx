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
    shape: 'rect',
    desc: 'Generates interaction bindings between charts'
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

function AgentShape({ type, color, active, hasContent }) {
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
        {AGENT_META[type]?.icon || '?'}
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

function buildSyntheticItems(agentId, planNodes) {
  if (agentId === 'plan') {
    return [
      { id: 'plan-refine', label: 'Refining requirements', status: 'success' },
      { id: 'plan-nodes', label: 'Generating nodes & dependencies', status: 'processing' }
    ]
  }
  if (agentId === 'data' && planNodes?.D) {
    return planNodes.D.map((n, idx) => ({
      id: `data-${n.id}`,
      label: `Process ${n.id}${n.name ? ': ' + n.name : ''}`,
      status: idx === 0 ? 'processing' : 'pending'
    }))
  }
  if (agentId === 'vis' && planNodes?.V) {
    return planNodes.V.map((n, idx) => ({
      id: `vis-${n.id}`,
      label: `Generate ${n.id}${n.name ? ': ' + n.name : ''}`,
      status: idx === 0 ? 'processing' : 'pending'
    }))
  }
  if (agentId === 'interaction' && planNodes?.I) {
    return planNodes.I.map((n, idx) => ({
      id: `interaction-${n.id}`,
      label: `Process ${n.id}${n.name ? ': ' + n.name : ''}`,
      status: idx === 0 ? 'processing' : 'pending'
    }))
  }
  if (agentId === 'error') {
    return [{ id: 'error-check', label: 'Checking for errors', status: 'processing' }]
  }
  return []
}

function AgentFlow({ agents, connections, activeAgent, expandedAgent, onToggleExpand, generating, planNodes }) {
  const agentOrder = ['plan', 'data', 'vis', 'interaction', 'error']

  const hasPlanNodes = (id, pn) => {
    const map = { data: 'D', vis: 'V', interaction: 'I' }
    const key = map[id]
    return key ? (pn[key]?.length > 0) : false
  }

  const visibleAgents = generating
    ? agentOrder
    : (agents
        ? agentOrder.filter(id => agents[id] || (planNodes && hasPlanNodes(id, planNodes)))
        : [])

  if (visibleAgents.length === 0) return null

  const isExpanded = (id) => {
    if (generating) return id === activeAgent
    return expandedAgent === id
  }

  const getAgentData = (id) => {
    if (agents?.[id]) return agents[id]
    if (!generating) return null
    return { items: [] }
  }

  const getItems = (id) => {
    const realAgent = agents?.[id]
    if (realAgent?.items?.length > 0) return realAgent.items
    if (!generating || id !== activeAgent) return []
    return buildSyntheticItems(id, planNodes)
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
          {visibleAgents.map((id, idx) => {
            const agent = getAgentData(id)
            const meta = AGENT_META[id] || {}
            const isActive = activeAgent === id
            const exp = isExpanded(id)
            const items = getItems(id)

            return (
              <div key={id} className="agent-node-wrapper">
                {idx > 0 && (
                  <div className={`agent-connector ${id === 'error' && items?.length > 0 ? 'connector-error' : ''}`}>
                    <div className="connector-line" />
                    <div className="connector-arrow" />
                  </div>
                )}
                <div
                  className={`agent-node ${isActive ? 'agent-active' : ''} ${exp ? 'agent-expanded' : ''}`}
                  onClick={() => onToggleExpand && onToggleExpand(id)}
                >
                  <AgentShape
                    type={meta.shape || 'circle'}
                    color={meta.color}
                    active={isActive}
                    hasContent={items.length > 0}
                  />
                  <div className="agent-name" style={{ color: meta.color }}>
                    {meta.name}
                  </div>
                  {isActive && generating && (
                    <div className="agent-status-label">{meta.desc}</div>
                  )}
                  {items.length > 0 && !(isActive && generating) && (
                    <div className="agent-item-count">
                      {items.length} item{items.length > 1 ? 's' : ''}
                    </div>
                  )}
                </div>

                {exp && items.length > 0 && (
                  <div className="agent-detail-panel">
                    {items.map(item => (
                      <AgentItem key={item.id} item={item} isProcessing={item.status === 'processing'} />
                    ))}
                  </div>
                )}
                {exp && items.length === 0 && (
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
