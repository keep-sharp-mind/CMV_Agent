import { useEffect, useRef, useState } from 'react'
import * as d3 from 'd3'

const NODE_CONFIG = {
  d: { radius: 14, color: '#0ea5e9', labelColor: '#fff', chargeStrength: -180, baseOpacity: 0.5 },
  D: { radius: 22, color: '#f59e0b', labelColor: '#fff', chargeStrength: -280, baseOpacity: 0.7 },
  V: { radius: 32, color: '#10b981', labelColor: '#fff', chargeStrength: -450, baseOpacity: 1 },
  I: { radius: 18, color: '#8b5cf6', labelColor: '#fff', chargeStrength: -220, baseOpacity: 0.6 },
}

function getNodeType(nodeId) {
  const firstChar = nodeId.charAt(0)
  if (firstChar === 'd') return 'd'
  if (firstChar === 'D') return 'D'
  if (firstChar === 'V') return 'V'
  if (firstChar === 'I') return 'I'
  return 'D'
}

function applySelectionOpacity({ link, arrow, node, label, linkData, selected }) {
  if (!link || !arrow || !node || !label) return

  const isConnectedToSelected = (d) => {
    const sourceId = d.source ? (d.source.id || d.source) : null
    const targetId = d.target ? (d.target.id || d.target) : null
    return sourceId === selected || targetId === selected
  }

  link.attr('stroke-opacity', d => {
    if (!selected) return 0.15
    return isConnectedToSelected(d) ? 1 : 0.04
  })

  arrow.attr('opacity', d => {
    if (!selected) return 0.3
    return isConnectedToSelected(d) ? 1 : 0.04
  })

  node.attr('opacity', d => {
    if (!selected) return NODE_CONFIG[d.type].baseOpacity
    if (d.id === selected) return 1
    const isAdjacent = linkData.some(l => {
      const sId = l.source.id || l.source
      const tId = l.target.id || l.target
      return (sId === selected && tId === d.id) || (tId === selected && sId === d.id)
    })
    return isAdjacent ? 1 : 0.12
  })

  label.attr('opacity', d => {
    if (!selected) return NODE_CONFIG[d.type].baseOpacity
    if (d.id === selected) return 1
    const isAdjacent = linkData.some(l => {
      const sId = l.source.id || l.source
      const tId = l.target.id || l.target
      return (sId === selected && tId === d.id) || (tId === selected && sId === d.id)
    })
    return isAdjacent ? 1 : 0.12
  })
}

function DependencyGraph({ nodes, dependencies, activeNodes = [], width = 700, height = 450, onNodeSelect, disabled = false }) {
  const svgRef = useRef(null)
  const containerRef = useRef(null)
  const linkRef = useRef(null)
  const arrowRef = useRef(null)
  const nodeRef = useRef(null)
  const labelRef = useRef(null)
  const linkDataRef = useRef([])
  const prevWidthRef = useRef(width)
  const dimensionsRef = useRef({ width, height })
  const [renderKey, setRenderKey] = useState(0)
  const [tooltip, setTooltip] = useState({ visible: false, x: 0, y: 0, content: null })
  const [selectedNodeId, setSelectedNodeId] = useState(null)
  const selectedRef = useRef(null)
  const onNodeSelectRef = useRef(onNodeSelect)
  const disabledRef = useRef(disabled)

  useEffect(() => {
    selectedRef.current = selectedNodeId
  }, [selectedNodeId])

  useEffect(() => {
    onNodeSelectRef.current = onNodeSelect
  }, [onNodeSelect])

  useEffect(() => {
    disabledRef.current = disabled
  }, [disabled])

  useEffect(() => {
    if (!containerRef.current) return
    const resizeObserver = new ResizeObserver(entries => {
      for (const entry of entries) {
        const newWidth = entry.contentRect.width
        const prev = prevWidthRef.current
        if (Math.abs(newWidth - prev) > 1) {
          prevWidthRef.current = newWidth
          dimensionsRef.current = { width: Math.max(400, newWidth), height: Math.max(300, newWidth * 0.6) }
          setRenderKey(k => k + 1)
        }
      }
    })
    resizeObserver.observe(containerRef.current)
    return () => resizeObserver.disconnect()
  }, [])

  useEffect(() => {
    if (!svgRef.current || !nodes || !dependencies) return

    const svg = d3.select(svgRef.current)
    svg.selectAll('*').remove()

    const { width: w, height: h } = dimensionsRef.current

    const allNodes = Object.values(nodes).flat()
    const nodeData = allNodes.map(n => {
      const type = getNodeType(n.id)
      const config = NODE_CONFIG[type]
      return {
        id: n.id,
        name: n.name,
        description: n.description,
        type,
        radius: config.radius,
        color: config.color,
        ...n,
      }
    })

    const linkData = dependencies.map(d => ({
      source: d.from,
      target: d.to,
      type: d.type,
    }))

    linkDataRef.current = linkData

    const simulation = d3.forceSimulation(nodeData)
      .force('link', d3.forceLink(linkData).id(d => d.id).distance(130).strength(0.8))
      .force('charge', d3.forceManyBody().strength(d => NODE_CONFIG[d.type].chargeStrength).distanceMax(250))
      .force('center', d3.forceCenter(w / 2, h / 2).strength(0.12))
      .force('collision', d3.forceCollide().radius(d => d.radius + 18).strength(0.8).iterations(3))
      .force('vCenterX', d3.forceX(w / 2).strength(d => d.type === 'V' ? 0.12 : 0.02))
      .force('vCenterY', d3.forceY(h / 2).strength(d => d.type === 'V' ? 0.12 : 0.02))
      .alphaDecay(0.06)
      .velocityDecay(0.7)
      .alphaMin(0.005)

    svg.append('rect')
      .attr('width', w)
      .attr('height', h)
      .attr('fill', 'transparent')
      .on('click', () => {
        if (disabledRef.current) return
        setSelectedNodeId(null)
        if (onNodeSelectRef.current) onNodeSelectRef.current(null)
      })

    const linkGroup = svg.append('g').attr('class', 'links')
    const arrowGroup = svg.append('g').attr('class', 'arrows')
    const nodeGroup = svg.append('g').attr('class', 'nodes')
    const labelGroup = svg.append('g').attr('class', 'labels')

    const link = linkGroup.selectAll('line')
      .data(linkData)
      .enter()
      .append('line')
      .attr('class', d => `link link-${d.type.replace('->', '-')}`)
      .attr('stroke', d => {
        if (d.type === 'V->I') return '#8b5cf6'
        if (d.type === 'I->V') return '#ec4899'
        if (d.type === 'D->V') return '#f59e0b'
        return '#0ea5e9'
      })
      .attr('stroke-width', 1.5)
      .attr('stroke-opacity', 0.15)

    const arrow = arrowGroup.selectAll('path')
      .data(linkData)
      .enter()
      .append('path')
      .attr('class', d => `arrow arrow-${d.type.replace('->', '-')}`)
      .attr('fill', d => {
        if (d.type === 'V->I') return '#8b5cf6'
        if (d.type === 'I->V') return '#ec4899'
        if (d.type === 'D->V') return '#f59e0b'
        return '#0ea5e9'
      })
      .attr('opacity', 0.3)
      .attr('pointer-events', 'none')

    const node = nodeGroup.selectAll('circle')
      .data(nodeData)
      .enter()
      .append('circle')
      .attr('class', d => `node node-${d.type}`)
      .attr('r', d => d.radius)
      .attr('fill', d => d.color)
      .attr('stroke', '#fff')
      .attr('stroke-width', 2)
      .attr('opacity', d => NODE_CONFIG[d.type].baseOpacity)
      .style('cursor', disabled ? 'not-allowed' : 'pointer')

    node.append('title').text(d => d.id + ': ' + d.name)

    const label = labelGroup.selectAll('text')
      .data(nodeData)
      .enter()
      .append('text')
      .attr('class', d => `node-label label-${d.type}`)
      .attr('text-anchor', 'middle')
      .attr('dominant-baseline', 'central')
      .attr('font-size', d => d.type === 'V' ? 11 : 10)
      .attr('font-weight', 600)
      .attr('fill', d => NODE_CONFIG[d.type].labelColor)
      .attr('opacity', d => NODE_CONFIG[d.type].baseOpacity)
      .attr('pointer-events', 'none')
      .text(d => d.id)

    linkRef.current = link
    arrowRef.current = arrow
    nodeRef.current = node
    labelRef.current = label

    node.on('mouseover', function(event, d) {
      const [x, y] = d3.pointer(event, containerRef.current)
      setTooltip({
        visible: true,
        x: x + 15,
        y: y + 15,
        content: {
          id: d.id,
          name: d.name,
          description: d.description,
          type: d.type,
          task: d.task,
          chart_type: d.chart_type,
          trigger: d.trigger,
          effect: d.effect,
          source_table: d.source_table,
        }
      })
    })

    node.on('mousemove', function(event) {
      const [x, y] = d3.pointer(event, containerRef.current)
      setTooltip(prev => ({ ...prev, x: x + 15, y: y + 15 }))
    })

    node.on('mouseout', function() {
      setTooltip({ visible: false, x: 0, y: 0, content: null })
    })

    node.on('click', function(event, d) {
      event.stopPropagation()
      if (disabledRef.current) return
      const currentSelected = selectedRef.current
      const nextId = currentSelected === d.id ? null : d.id
      setSelectedNodeId(nextId)
      if (onNodeSelectRef.current) {
        onNodeSelectRef.current(nextId ? nodeData.find(n => n.id === nextId) || null : null)
      }
    })

    simulation.on('tick', () => {
      link
        .attr('x1', d => d.source.x)
        .attr('y1', d => d.source.y)
        .attr('x2', d => {
          const dx = d.target.x - d.source.x
          const dy = d.target.y - d.source.y
          const dist = Math.sqrt(dx * dx + dy * dy) || 1
          const offset = d.target.radius + 4
          return d.target.x - (dx / dist) * offset
        })
        .attr('y2', d => {
          const dx = d.target.x - d.source.x
          const dy = d.target.y - d.source.y
          const dist = Math.sqrt(dx * dx + dy * dy) || 1
          const offset = d.target.radius + 4
          return d.target.y - (dy / dist) * offset
        })

      arrow
        .attr('d', d => {
          const dx = d.target.x - d.source.x
          const dy = d.target.y - d.source.y
          const dist = Math.sqrt(dx * dx + dy * dy) || 1
          const offset = d.target.radius + 4
          const tipX = d.target.x - (dx / dist) * offset
          const tipY = d.target.y - (dy / dist) * offset
          const angle = Math.atan2(dy, dx)
          const arrowSize = 5
          const back1x = tipX - arrowSize * Math.cos(angle - Math.PI / 6)
          const back1y = tipY - arrowSize * Math.sin(angle - Math.PI / 6)
          const back2x = tipX - arrowSize * Math.cos(angle + Math.PI / 6)
          const back2y = tipY - arrowSize * Math.sin(angle + Math.PI / 6)
          return `M${back1x},${back1y} L${tipX},${tipY} L${back2x},${back2y}Z`
        })

      node
        .attr('cx', d => Math.max(d.radius, Math.min(w - d.radius, d.x)))
        .attr('cy', d => Math.max(d.radius, Math.min(h - d.radius, d.y)))

      label
        .attr('x', d => Math.max(d.radius, Math.min(w - d.radius, d.x)))
        .attr('y', d => Math.max(d.radius, Math.min(h - d.radius, d.y)))
    })

    simulation.on('end', () => {
      simulation.stop()
    })

    return () => {
      simulation.stop()
    }
  }, [nodes, dependencies, renderKey, disabled])

  useEffect(() => {
    applySelectionOpacity({
      link: linkRef.current,
      arrow: arrowRef.current,
      node: nodeRef.current,
      label: labelRef.current,
      linkData: linkDataRef.current,
      selected: selectedNodeId,
    })
  }, [selectedNodeId])

  useEffect(() => {
    if (!nodeRef.current) return
    nodeRef.current.classed('node-processing', d => activeNodes.includes(d.id))
  }, [activeNodes])

  return (
    <div
      className={`dependency-graph-container${disabled ? ' is-disabled' : ''}`}
      ref={containerRef}
      aria-disabled={disabled}
    >
      <svg ref={svgRef} width={dimensionsRef.current.width} height={dimensionsRef.current.height} />
      {tooltip.visible && tooltip.content && (
        <div
          className="graph-tooltip"
          style={{ left: tooltip.x, top: tooltip.y }}
        >
          <div className="tooltip-header">
            <span className={`tooltip-type-badge type-${tooltip.content.type}`}>
              {tooltip.content.type}
            </span>
            <span className="tooltip-id">{tooltip.content.id}</span>
          </div>
          <div className="tooltip-name">{tooltip.content.name}</div>
          <div className="tooltip-desc">{tooltip.content.description}</div>
          {tooltip.content.task && (
            <div className="tooltip-task">
              <strong>Task:</strong> {tooltip.content.task}
            </div>
          )}
          {tooltip.content.chart_type && (
            <div className="tooltip-meta">
              <strong>Chart:</strong> {tooltip.content.chart_type}
            </div>
          )}
          {tooltip.content.trigger && (
            <div className="tooltip-meta">
              <strong>Trigger:</strong> {tooltip.content.trigger} | <strong>Effect:</strong> {tooltip.content.effect}
            </div>
          )}
          {tooltip.content.source_table && (
            <div className="tooltip-meta">
              <strong>Source:</strong> {tooltip.content.source_table}
            </div>
          )}
        </div>
      )}

      <div className="graph-legend">
        <div className="legend-item">
          <span className="legend-dot" style={{ background: NODE_CONFIG.d.color }}></span>
          <span>d - Input Table</span>
        </div>
        <div className="legend-item">
          <span className="legend-dot" style={{ background: NODE_CONFIG.D.color }}></span>
          <span>D - Data Processing</span>
        </div>
        <div className="legend-item">
          <span className="legend-dot" style={{ background: NODE_CONFIG.V.color }}></span>
          <span>V - Visualization</span>
        </div>
        <div className="legend-item">
          <span className="legend-dot" style={{ background: NODE_CONFIG.I.color }}></span>
          <span>I - Interaction</span>
        </div>
      </div>
    </div>
  )
}

export default DependencyGraph
