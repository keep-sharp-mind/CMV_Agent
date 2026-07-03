import { useState, useEffect, useRef } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { getProject, updateProject, fetchDatabases, uploadDatabase, deleteDatabase, generateGoal, generatePlan, getPlan, processData, processSingleDNode, processSingleVNode, getNodeData, getNodeCode, getDataResult, getVisSpec, getAgentTrace, processInteractions, getDataFlow, getInteractionResult, resetProcessing } from '../api'
import DependencyGraph from '../components/DependencyGraph'
import ProjectInfoSection from '../components/ProjectInfoSection'
import DatabaseSection from '../components/DatabaseSection'
import NodeCard from '../components/NodeCard'
import NodeDetailSection from '../components/NodeDetailSection'
import AgentFlow from '../components/AgentFlow'
import DataFlowTable from '../components/DataFlowTable'
import ChartPreview from '../components/ChartPreview'
import vegaEmbed from 'vega-embed'

const NODE_TYPE_LABELS = {
  d: 'Input Tables',
  D: 'Data Processing',
  V: 'Visualization',
  I: 'Interaction'
}

function NodeGroup({ label, type, nodes }) {
  if (!nodes || nodes.length === 0) return null
  const badgeClass = `${type.toLowerCase()}-badge`
  return (
    <div className="node-group">
      <h4 className={`node-group-title ${type}-node-title`}>
        <span className={`node-type-badge ${badgeClass}`}>{type}</span>
        {label} ({nodes.length})
      </h4>
      <div className="nodes-grid">
        {nodes.map(node => (
          <NodeCard key={node.id} node={node} type={type.toLowerCase()} />
        ))}
      </div>
    </div>
  )
}

function RefinedRequirements({ requirements }) {
  if (!requirements || requirements.length === 0) return null
  return (
    <div className="plan-subsection">
      <h3>Refined Requirements</h3>
      <div className="requirements-list">
        {requirements.map(req => (
          <div key={req.id} className="requirement-card">
            <div className="req-id">{req.id}</div>
            <div className="req-body">
              <div className="req-name">{req.name}</div>
              <div className="req-desc">{req.description}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function getNodeType(nodeId) {
  const firstChar = nodeId.charAt(0)
  if (firstChar === 'd') return 'd'
  if (firstChar === 'D') return 'D'
  if (firstChar === 'V') return 'V'
  if (firstChar === 'I') return 'I'
  return 'D'
}

function topologicalSort(nodeIds, dependencies) {
  const graph = {}
  const inDegree = {}
  if (!nodeIds) return []
  nodeIds.forEach(id => {
    graph[id] = []
    inDegree[id] = 0
  })
  ;(dependencies || []).forEach(dep => {
    if (graph[dep.from] !== undefined && inDegree[dep.to] !== undefined) {
      graph[dep.from].push(dep.to)
      inDegree[dep.to]++
    }
  })
  const queue = nodeIds.filter(id => inDegree[id] === 0)
  const result = []
  while (queue.length > 0) {
    const node = queue.shift()
    result.push(node)
    ;(graph[node] || []).forEach(neighbor => {
      inDegree[neighbor]--
      if (inDegree[neighbor] === 0) queue.push(neighbor)
    })
  }
  return result
}

function ProjectDetail() {
  const { projectId } = useParams()
  const navigate = useNavigate()
  const fileInputRef = useRef(null)

  const [project, setProject] = useState(null)
  const [isEditing, setIsEditing] = useState(false)
  const [editName, setEditName] = useState('')
  const [editGoal, setEditGoal] = useState('')
  const [databases, setDatabases] = useState([])
  const [isUploading, setIsUploading] = useState(false)
  const [error, setError] = useState(null)
  const [expandedDb, setExpandedDb] = useState(null)
  const [isPlanning, setIsPlanning] = useState(false)
  const [planResult, setPlanResult] = useState(null)
  const [isProcessingData, setIsProcessingData] = useState(false)
  const [isGenerating, setIsGenerating] = useState(false)
  const [dataResult, setDataResult] = useState(null)
  const [selectedGraphNode, setSelectedGraphNode] = useState(null)
  const [nodeTableData, setNodeTableData] = useState(null)
  const [isLoadingNodeData, setIsLoadingNodeData] = useState(false)
  const [nodeCode, setNodeCode] = useState(null)
  const [showCode, setShowCode] = useState(false)
  const [isLoadingNodeCode, setIsLoadingNodeCode] = useState(false)
  const [visSpec, setVisSpec] = useState(null)
  const [showVisCode, setShowVisCode] = useState(false)
  const [interactionSpec, setInteractionSpec] = useState(null)
  const [showInteractionCode, setShowInteractionCode] = useState(false)
  const chartContainerRef = useRef(null)
  const chartRenderedRef = useRef(false)
  const [agentTrace, setAgentTrace] = useState(null)
  const [expandedAgent, setExpandedAgent] = useState(null)
  const [activeAgent, setActiveAgent] = useState(null)
  const [activeNodes, setActiveNodes] = useState([])
  const agentTimerRef = useRef(null)
  const [isProcessingInteractions, setIsProcessingInteractions] = useState(false)
  const [interactionResults, setInteractionResults] = useState(null)
  const [viewDataUrls, setViewDataUrls] = useState(null)
  const [nodeDataFlow, setNodeDataFlow] = useState(null)

  useEffect(() => {
    loadProject()
    loadDatabases()
    loadPlan()
    loadDataResult()
    loadAgentTrace()

    return () => {
      if (agentTimerRef.current) {
        clearTimeout(agentTimerRef.current)
      }
    }
  }, [projectId])

  const loadPlan = async () => {
    try {
      const data = await getPlan(projectId)
      if (data) {
        setPlanResult(data)
      }
    } catch (err) {
      // no error when plan doesn't exist
    }
  }

  const loadDataResult = async () => {
    try {
      const data = await getDataResult(projectId)
      if (data) {
        setDataResult(data)
      }
    } catch (err) {
      // no error when data result doesn't exist
    }
  }

  const loadAgentTrace = async () => {
    try {
      const data = await getAgentTrace(projectId)
      if (data) {
        setAgentTrace(data)
      }
    } catch (err) {
      // no error when trace doesn't exist
    }
  }

  const loadProject = async () => {
    try {
      const data = await getProject(projectId)
      setProject(data)
      setEditName(data.name)
      setEditGoal(data.goal)
    } catch (err) {
      setError(`Failed to load project: ${err.message}`)
    }
  }

  const loadDatabases = async () => {
    try {
      const data = await fetchDatabases(projectId)
      setDatabases(data)
    } catch (err) {
      setError(`Failed to load databases: ${err.message}`)
    }
  }

  const handleSave = async () => {
    try {
      const updated = await updateProject(projectId, {
        name: editName.trim(),
        goal: editGoal.trim()
      })
      setProject(updated)
      setIsEditing(false)
      setError(null)
    } catch (err) {
      setError(`Failed to update project: ${err.message}`)
    }
  }

  const handleCancel = () => {
    setEditName(project.name)
    setEditGoal(project.goal)
    setIsEditing(false)
  }

  const handleFileUpload = async (e) => {
    const files = Array.from(e.target.files)
    if (files.length === 0) return

    setIsUploading(true)
    setError(null)

    try {
      for (const file of files) {
        await uploadDatabase(projectId, file)
      }
      await loadDatabases()
    } catch (err) {
      setError(`Failed to upload database: ${err.message}`)
    } finally {
      setIsUploading(false)
      if (fileInputRef.current) {
        fileInputRef.current.value = ''
      }
    }
  }

  const handleDeleteDatabase = async (dbName) => {
    if (!confirm(`Are you sure you want to delete "${dbName}"?`)) return

    try {
      await deleteDatabase(projectId, dbName)
      setDatabases(databases.filter(db => db.db_name !== dbName))
      if (expandedDb === dbName) {
        setExpandedDb(null)
      }
    } catch (err) {
      setError(`Failed to delete database: ${err.message}`)
    }
  }

  const toggleDbExpand = (dbName) => {
    setExpandedDb(expandedDb === dbName ? null : dbName)
  }

  const handleGeneratePlan = async () => {
    // Clear previous generated content
    setDataResult(null)
    setVisSpec(null)
    setNodeTableData(null)
    setNodeCode(null)
    setShowCode(false)
    setSelectedGraphNode(null)
    setAgentTrace(null)

    setIsPlanning(true)
    setError(null)
    setActiveAgent('plan')

    try {
      const result = await generatePlan(projectId)
      setPlanResult(result)

      if (result.goal && project.goal !== result.goal) {
        setProject(prev => ({ ...prev, goal: result.goal }))
        setEditGoal(result.goal)
      }
    } catch (err) {
      setError(`Failed to generate plan: ${err.message}`)
    } finally {
      setIsPlanning(false)
      setActiveAgent(null)
    }
  }

  const handleGenerate = async () => {
    // Clear all previously generated content
    setDataResult(null)
    setVisSpec(null)
    setNodeTableData(null)
    setNodeCode(null)
    setShowCode(false)
    setSelectedGraphNode(null)
    setAgentTrace(null)
    setActiveNodes([])

    // Clear backend processing artifacts (keep plan)
    try { await resetProcessing(projectId) } catch (_) {}

    setIsGenerating(true)
    setError(null)
    setActiveAgent('plan')

    // Step 1: Generate plan if needed
    let planData = planResult
    if (!planData) {
      try {
        const result = await generatePlan(projectId)
        setPlanResult(result)
        planData = result
        if (result.goal && project.goal !== result.goal) {
          setProject(prev => ({ ...prev, goal: result.goal }))
          setEditGoal(result.goal)
        }
      } catch (err) {
        setError(`Plan generation failed: ${err.message}`)
        setIsGenerating(false)
        setActiveAgent(null)
        return
      }
    }

    setIsProcessingData(true)

    // Step 2: Process D nodes one by one
    const planNodes = planData?.nodes
    const dNodes = topologicalSort(
      (planNodes?.D || []).map(n => n.id),
      planData?.dependencies
    )
    const vNodes = (planNodes?.V || []).map(n => n.id)

    setActiveAgent('data')

    const allProcessedNodes = {}
    try {
      for (const nodeId of dNodes) {
        setActiveNodes([nodeId])
        const result = await processSingleDNode(projectId, nodeId)
        allProcessedNodes[nodeId] = result
        loadDataFlow()
      }

      // Step 3: Process V nodes one by one
      if (vNodes.length > 0) {
        setActiveAgent('vis')
        for (const nodeId of vNodes) {
          setActiveNodes([nodeId])
          const result = await processSingleVNode(projectId, nodeId)
          allProcessedNodes[nodeId] = result
          loadDataFlow()
        }
      }

      // Load accumulated result
      const result = await getDataResult(projectId)
      setDataResult(result)

      // Step 4: Process interactions (if I nodes exist)
      const iNodes = planData?.nodes?.I
      if (iNodes && iNodes.length > 0) {
        setActiveAgent('interaction')
        setActiveNodes(iNodes.map(n => n.id))
        try {
          const interactionResult = await processInteractions(projectId)
          setInteractionResults(interactionResult.interaction_results || {})
          setViewDataUrls(interactionResult.view_data_urls || {})
          const updated = await getDataResult(projectId)
          setDataResult(updated)
          loadDataFlow()
        } catch (interr) {
          console.warn('Interaction processing failed:', interr.message)
        }
      }
    } catch (err) {
      setError(`Data processing failed: ${err.message}`)
    } finally {
      loadDataFlow()
      setActiveAgent(null)
      setActiveNodes([])
      setIsProcessingData(false)
      setIsGenerating(false)
      loadAgentTrace()
    }
  }

  const handleProcessData = async () => {
    // Clear previously generated data results
    setDataResult(null)
    setVisSpec(null)
    setNodeTableData(null)
    setNodeCode(null)
    setShowCode(false)
    setSelectedGraphNode(null)
    setAgentTrace(null)
    setActiveNodes([])

    // Clear backend processing artifacts (keep plan)
    try { await resetProcessing(projectId) } catch (_) {}

    setIsProcessingData(true)
    setError(null)
    setActiveAgent('data')

    const planNodes = planResult?.nodes
    const dNodes = topologicalSort(
      (planNodes?.D || []).map(n => n.id),
      planResult?.dependencies
    )
    const vNodes = (planNodes?.V || []).map(n => n.id)

    try {
      for (const nodeId of dNodes) {
        setActiveNodes([nodeId])
        await processSingleDNode(projectId, nodeId)
        loadDataFlow()
      }

      if (vNodes.length > 0) {
        setActiveAgent('vis')
        for (const nodeId of vNodes) {
          setActiveNodes([nodeId])
          await processSingleVNode(projectId, nodeId)
          loadDataFlow()
        }
      }

      const result = await getDataResult(projectId)
      setDataResult(result)

      const iNodes = planResult?.nodes?.I
      if (iNodes && iNodes.length > 0) {
        setActiveAgent('interaction')
        setActiveNodes(iNodes.map(n => n.id))
        try {
          const interactionResult = await processInteractions(projectId)
          setInteractionResults(interactionResult.interaction_results || {})
          setViewDataUrls(interactionResult.view_data_urls || {})
          const updated = await getDataResult(projectId)
          setDataResult(updated)
          loadDataFlow()
        } catch (interr) {
          console.warn('Interaction processing failed:', interr.message)
        }
      }
    } catch (err) {
      setError(`Failed to process data: ${err.message}`)
    } finally {
      loadDataFlow()
      setActiveAgent(null)
      setActiveNodes([])
      setIsProcessingData(false)
      loadAgentTrace()
    }
  }

  const loadDataFlow = async () => {
    try {
      const flow = await getDataFlow(projectId)
      setNodeDataFlow(flow)
    } catch (_) {}
  }

  const handleNodeSelect = async (node) => {
    setSelectedGraphNode(node)
    setNodeCode(null)
    setShowCode(false)
    setVisSpec(null)
    setShowVisCode(false)
    chartRenderedRef.current = false

    if (!node) {
      setNodeTableData(null)
      setNodeDataFlow(null)
      return
    }

    loadDataFlow()

    if (node.type === 'd' || node.type === 'D') {
      setIsLoadingNodeData(true)
      setNodeTableData(null)
      try {
        const data = await getNodeData(projectId, node.id)
        setNodeTableData(data)
      } catch (err) {
        // silently fail
      } finally {
        setIsLoadingNodeData(false)
      }
    } else if (node.type === 'V') {
      setNodeTableData(null)
      const visData = dataResult?.processed_vis?.[node.id]
      if (visData) {
        setVisSpec(visData)
        chartRenderedRef.current = false
      }
    } else if (node.type === 'I') {
      setNodeTableData(null)
      setVisSpec(null)
      setInteractionSpec(null)
      setShowInteractionCode(false)
      try {
        const iData = await getInteractionResult(projectId, node.id)
        setInteractionSpec(iData)
      } catch (_) {
        setInteractionSpec(null)
      }
    } else {
      setNodeTableData(null)
    }
  }

  const handleShowVisCode = (nodeId) => {
    if (visSpec) {
      setShowVisCode(!showVisCode)
      return
    }
    setVisSpec({ spec_json: 'Loading...' })
    getVisSpec(projectId, nodeId).then(data => {
      setVisSpec(data)
      setShowVisCode(true)
    }).catch(err => {
      setError(`Failed to load visualization: ${err.message}`)
    })
  }

  useEffect(() => {
    if (!visSpec || !visSpec.spec) return
    if (chartRenderedRef.current) return

    const container = chartContainerRef.current
    if (!container) return

    chartRenderedRef.current = true

    // Clear previous content
    container.innerHTML = ''

    const spec = visSpec.spec

    vegaEmbed(container, spec, {
      actions: { export: true, source: false, compiled: false, editor: false },
      renderer: 'canvas',
      tooltip: true
    }).catch(err => {
      console.error('Vega-Embed error:', err)
      // Allow retry on next spec change
      chartRenderedRef.current = false
    })
  }, [visSpec])

  const handleShowCode = async (nodeId) => {
    if (nodeCode) {
      setShowCode(!showCode)
      return
    }

    setIsLoadingNodeCode(true)
    try {
      const data = await getNodeCode(projectId, nodeId)
      setNodeCode(data.code)
      setShowCode(true)
    } catch (err) {
      setError(`Failed to load code: ${err.message}`)
    } finally {
      setIsLoadingNodeCode(false)
    }
  }

  if (!project) {
    return (
      <div className="project-detail-container">
        <div className="loading">Loading project...</div>
      </div>
    )
  }

  const allNodes = planResult?.nodes
    ? Object.values(planResult.nodes).flat()
    : []

  return (
    <div className="project-detail-container">
      <div className="project-detail-header">
        <button className="back-button" onClick={() => navigate('/')}>
          ← Back to Projects
        </button>
        <h1>Project Details</h1>
      </div>

      {error && <div className="error-message">{error}</div>}

      <ProjectInfoSection
        project={project}
        isEditing={isEditing}
        editName={editName}
        editGoal={editGoal}
        onStartEdit={() => setIsEditing(true)}
        onCancel={handleCancel}
        onSave={handleSave}
        onNameChange={setEditName}
        onGoalChange={setEditGoal}
      />

      <DatabaseSection
        databases={databases}
        expandedDb={expandedDb}
        isUploading={isUploading}
        onUpload={handleFileUpload}
        onDelete={handleDeleteDatabase}
        onToggleExpand={toggleDbExpand}
        fileInputRef={fileInputRef}
      />

      <div className="plan-section">
        <div className="section-header">
          <h2>Analysis Plan</h2>
          <button
            className="primary-button"
            onClick={handleGeneratePlan}
            disabled={isPlanning || databases.length === 0}
          >
            {isPlanning ? 'Generating...' : planResult ? 'Regenerate' : 'Generate Plan'}
          </button>
        </div>

        {planResult && (
          <div className="plan-content">
            <RefinedRequirements requirements={planResult.refined_requirements} />

            {planResult.nodes && (
              <div className="plan-subsection">
                <h3>Nodes</h3>
                <NodeGroup label={NODE_TYPE_LABELS.d} type="d" nodes={planResult.nodes.d} />
                <NodeGroup label={NODE_TYPE_LABELS.D} type="D" nodes={planResult.nodes.D} />
                <NodeGroup label={NODE_TYPE_LABELS.V} type="V" nodes={planResult.nodes.V} />
                <NodeGroup label={NODE_TYPE_LABELS.I} type="I" nodes={planResult.nodes.I} />
              </div>
            )}

            {planResult.dependencies && planResult.dependencies.length > 0 && (
              <div className="plan-subsection">
                <AgentFlow
                  agents={agentTrace?.agents || null}
                  connections={agentTrace?.connections || null}
                  activeAgent={activeAgent}
                  expandedAgent={expandedAgent}
                  onToggleExpand={(id) => setExpandedAgent(expandedAgent === id ? null : id)}
                  generating={isGenerating || isProcessingData}
                  planNodes={planResult?.nodes}
                />

                <div className="section-header" style={{ marginTop: '20px' }}>
                  <h3>Dependency Graph</h3>
                  <button
                    className="primary-button"
                    onClick={handleGenerate}
                    disabled={isGenerating || isProcessingData || !planResult.nodes?.D?.length}
                    style={{ fontSize: '0.85rem', padding: '6px 12px' }}
                  >
                    {isGenerating || isProcessingData ? 'Generating...' : 'Generate'}
                  </button>
                </div>
                <DependencyGraph
                  nodes={planResult.nodes}
                  dependencies={planResult.dependencies}
                  onNodeSelect={handleNodeSelect}
                  selectedNodeId={selectedGraphNode?.id || null}
                  activeNodes={activeNodes}
                />

                {selectedGraphNode && (
                  <NodeDetailSection
                    node={selectedGraphNode}
                    nodeTableData={nodeTableData}
                    isLoadingNodeData={isLoadingNodeData}
                    dataResult={dataResult}
                    visSpec={visSpec}
                    showCode={showCode}
                    nodeCode={nodeCode}
                    isLoadingNodeCode={isLoadingNodeCode}
                    onToggleCode={() => handleShowCode(selectedGraphNode.id)}
                    showVisCode={showVisCode}
                    onToggleVisCode={() => handleShowVisCode(selectedGraphNode.id)}
                    chartContainerRef={chartContainerRef}
                    dataFlow={nodeDataFlow?.[selectedGraphNode.id] || null}
                    interactionSpec={interactionSpec}
                    showInteractionCode={showInteractionCode}
                    onToggleInteractionCode={() => setShowInteractionCode(!showInteractionCode)}
                  />
                )}

                <DataFlowTable
                  nodeDataFlow={nodeDataFlow}
                  planNodes={planResult?.nodes}
                />
              </div>
            )}
          </div>
        )}

        {dataResult?.processed_vis && Object.keys(dataResult.processed_vis).length > 0 && (
          <div className="plan-section">
            <div className="section-header">
              <h2>Visualizations Dashboard</h2>
              <button
                className="primary-button"
                onClick={async () => {
                  setIsProcessingInteractions(true)
                  try {
                    const result = await processInteractions(projectId)
                    setInteractionResults(result.interaction_results || {})
                    setViewDataUrls(result.view_data_urls || {})
                    const updated = await getDataResult(projectId)
                    setDataResult(updated)
                  } catch (err) {
                    setError(`Interaction processing failed: ${err.message}`)
                  } finally {
                    setIsProcessingInteractions(false)
                  }
                }}
                disabled={isProcessingInteractions}
                style={{ fontSize: '0.85rem', padding: '6px 12px' }}
              >
                {isProcessingInteractions ? 'Processing...' : 'Process Interactions'}
              </button>
            </div>
            <ChartPreview
              processedVis={dataResult.processed_vis}
              interactionResults={interactionResults}
              viewDataUrls={viewDataUrls}
            />
          </div>
        )}

        {!planResult && !isPlanning && (
          <div className="plan-empty">
            <p>No plan generated yet. Click "Generate Plan" to create one.</p>
          </div>
        )}
      </div>
    </div>
  )
}

export default ProjectDetail
