import { useState, useEffect, useRef } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { getProject, updateProject, fetchDatabases, uploadDatabase, deleteDatabase, generateGoal, generatePlan, getPlan, processData, processSingleDNode, processSingleVNode, getNodeData, getNodeCode, getDataResult, getVisSpec, getAgentTrace, processInteractions, getDataFlow, getInteractionResult, resetProcessing } from '../api'
import DependencyGraph from '../components/DependencyGraph'
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
    <div className="sidebar-subsection">
      <h4 className="sidebar-subsection-title">Refined Requirements</h4>
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

function getDependencyInput(nodeId, dependencies) {
  const inputs = (dependencies || [])
    .filter(dependency => dependency.to === nodeId)
    .map(dependency => dependency.from)
  return inputs.length > 0 ? inputs.join(', ') : 'database'
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
  const flowRunRef = useRef(0)
  const flowTimerRefs = useRef(new Set())
  const flowBusyRef = useRef(false)
  const [isProcessingInteractions, setIsProcessingInteractions] = useState(false)
  const [interactionResults, setInteractionResults] = useState(null)
  const [viewDataUrls, setViewDataUrls] = useState(null)
  const [nodeDataFlow, setNodeDataFlow] = useState(null)
  const [showNodes, setShowNodes] = useState(false)
  const [showViews, setShowViews] = useState(false)
  const [isFixing, setIsFixing] = useState(false)
  const [nodeStatus, setNodeStatus] = useState({})
  const [errorRetryEntries, setErrorRetryEntries] = useState([])

  useEffect(() => {
    loadProject()
    loadDatabases()
    loadPlan()
    loadDataResult()
    loadAgentTrace()

    return () => {
      flowRunRef.current += 1
      if (agentTimerRef.current) {
        clearTimeout(agentTimerRef.current)
      }
      flowTimerRefs.current.forEach(timerId => clearTimeout(timerId))
      flowTimerRefs.current.clear()
    }
  }, [projectId])

  const clearFlowTimers = () => {
    flowTimerRefs.current.forEach(timerId => clearTimeout(timerId))
    flowTimerRefs.current.clear()
  }

  const startFlowRun = () => {
    flowRunRef.current += 1
    clearFlowTimers()
    return flowRunRef.current
  }

  const isCurrentFlowRun = (runToken) => runToken === flowRunRef.current

  const waitForFlowRun = (durationMs, runToken) => (
    new Promise(resolve => {
      if (!isCurrentFlowRun(runToken)) {
        resolve(false)
        return
      }
      const timerId = setTimeout(() => {
        flowTimerRefs.current.delete(timerId)
        resolve(isCurrentFlowRun(runToken))
      }, durationMs)
      flowTimerRefs.current.add(timerId)
    })
  )

  const setActiveFlowState = (runToken, agentId, nodeIds = [], expandedId = agentId) => {
    if (!isCurrentFlowRun(runToken)) return false
    setActiveAgent(agentId)
    setExpandedAgent(expandedId)
    setActiveNodes(nodeIds)
    return true
  }

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

  const startNodeRun = (nodeId, input, output) => {
    setNodeStatus(previous => ({
      ...previous,
      [nodeId]: [{ status: 'processing', attempt: 1, input, output }]
    }))
  }

  const summarizeValidationIssues = (issues = []) => {
    if (!Array.isArray(issues) || issues.length === 0) return ''
    return issues
      .slice(0, 2)
      .map(issue => issue.detail || issue.type)
      .filter(Boolean)
      .join('; ')
  }

  const getResultErrorSummary = (result) => {
    return (
      result?.error ||
      result?.original_error ||
      result?.error_report?.summary ||
      result?.error_report?.original_error?.error ||
      summarizeValidationIssues(result?.validation_issues) ||
      summarizeValidationIssues(result?.error_report?.original_error?.validation_issues) ||
      'Validation failed'
    )
  }

  const clampReplayDelay = (durationMs, minMs, maxMs) => {
    const value = Number(durationMs)
    if (!Number.isFinite(value) || value <= 0) return minMs
    return Math.min(Math.max(value, minMs), maxMs)
  }

  const getAttemptDiagnosisDelay = (attempt) => {
    return clampReplayDelay(
      attempt?.diagnosis_duration_ms || attempt?.phase_timings?.diagnosis_ms,
      1400,
      7000
    )
  }

  const getAttemptRegenerationDelay = (attempt) => {
    return clampReplayDelay(
      attempt?.regeneration_duration_ms ||
      attempt?.phase_timings?.regeneration_ms ||
      attempt?.fix_generation_duration_ms ||
      attempt?.phase_timings?.fix_generation_ms,
      900,
      5000
    )
  }

  const normalizeRecoveryAttemptStatus = (attempt) => {
    const status = String(attempt?.status || '').toLowerCase()
    if (status === 'recovered' || status === 'success') return 'success'
    if (status === 'processing' || status === 'running' || status === 'in_progress') return 'processing'
    if (
      !status ||
      status.includes('failed') ||
      status.includes('rejected') ||
      status.includes('error') ||
      status.includes('invalid')
    ) {
      return 'error'
    }
    return 'error'
  }

  const buildErrorAgentEntries = (nodeId, result, agentLabel) => {
    const entries = []
    const errorReport = result?.error_report
    const recoveryAttempts = result?.recovery_attempts || errorReport?.recovery_attempts || []
    const recoveryStatus = errorReport?.recovery_status || {}
    const hasErrorFlow = Boolean(errorReport) || recoveryAttempts.length > 0 || result?.success === false

    if (!hasErrorFlow) return entries

    entries.push({
      id: `error-detect-${nodeId}`,
      label: `Detected issue in ${nodeId}`,
      status: result?.success === false ? 'error' : 'success',
      input: agentLabel,
      output: 'Send to Error Agent',
      error_detail: getResultErrorSummary(result)
    })

    if (errorReport?.summary) {
      entries.push({
        id: `error-diagnose-${nodeId}`,
        label: `Diagnose ${nodeId}`,
        status: 'success',
        input: 'Error context',
        output: 'Diagnosis',
        error_detail: errorReport.summary
      })
    }

    recoveryAttempts.forEach((attempt, index) => {
      const attemptStatus = normalizeRecoveryAttemptStatus(attempt)
      entries.push({
        id: `error-retry-${nodeId}-${index}`,
        label: `Regenerate ${nodeId} (attempt ${attempt.attempt || index + 1})`,
        status: attemptStatus,
        input: attempt.diagnosis?.root_cause || attempt.analysis?.root_cause || attempt.status || 'Diagnosis',
        output: attemptStatus === 'success' ? 'Recovered output' : 'Retry result',
        error_detail: attempt.error || attempt.execution_result?.error || attempt.result?.error || attempt.validation_error || attempt.fix_result?.error || attempt.fix?.error
      })
    })

    if (errorReport) {
      const recovered = recoveryStatus.recovered || result?.recovered
      entries.push({
        id: `error-final-${nodeId}`,
        label: `${nodeId} recovery result`,
        status: recovered ? 'success' : 'error',
        input: `${recoveryStatus.attempt_count ?? recoveryAttempts.length} attempt(s)`,
        output: recovered ? 'Recovered' : 'Needs attention',
        error_detail: recovered ? null : getResultErrorSummary(result)
      })
    }

    return entries
  }

  const handleNodeErrorFlow = async (nodeId, result, agentId, runToken) => {
    const entries = buildErrorAgentEntries(nodeId, result, agentId === 'data' ? 'Data Agent' : 'Vis Agent')
    if (entries.length === 0 || !isCurrentFlowRun(runToken)) return

    const recoveryAttempts = result?.recovery_attempts || result?.error_report?.recovery_attempts || []
    const detectionEntries = entries.filter(entry => !entry.label.startsWith('Regenerate'))
    const retryEntries = entries.filter(entry => entry.label.startsWith('Regenerate'))

    setErrorRetryEntries(previous => [...previous, ...detectionEntries])
    if (!setActiveFlowState(runToken, 'error', [nodeId], 'error')) return
    if (!await waitForFlowRun(800, runToken)) return

    for (let index = 0; index < retryEntries.length; index++) {
      if (!isCurrentFlowRun(runToken)) return
      const entry = retryEntries[index]
      const attempt = recoveryAttempts[index] || {}
      const attemptNo = attempt.attempt || index + 1
      const retryNodeId = `re_${nodeId}`

      const diagnosisEntry = {
        id: `error-diagnose-${nodeId}-${attemptNo}`,
        label: `Diagnose ${nodeId} (attempt ${attemptNo})`,
        status: 'processing',
        input: 'Error context',
        output: 'Root cause analysis',
        error_detail: attempt.diagnosis?.explanation || attempt.analysis?.explanation || getResultErrorSummary(result)
      }
      setErrorRetryEntries(previous => [...previous, diagnosisEntry])
      if (!setActiveFlowState(runToken, 'error', [nodeId], 'error')) return
      if (!await waitForFlowRun(getAttemptDiagnosisDelay(attempt), runToken)) return
      setErrorRetryEntries(previous => previous.map(item => (
        item.id === diagnosisEntry.id ? { ...diagnosisEntry, status: attempt.status === 'diagnosis_failed' ? 'error' : 'success' } : item
      )))

      setErrorRetryEntries(previous => [...previous, { ...entry, status: 'processing' }])
      if (!setActiveFlowState(runToken, agentId, [retryNodeId], agentId)) return
      setNodeStatus(previous => ({
        ...previous,
        [nodeId]: [
          ...(previous[nodeId] || []),
          {
            status: 'processing',
            attempt: attemptNo + 1,
            retryNodeId,
            input: entry.input,
            output: entry.output
          }
        ]
      }))
      if (!await waitForFlowRun(getAttemptRegenerationDelay(attempt), runToken)) return

      setErrorRetryEntries(previous => previous.map(item => (
        item.id === entry.id ? entry : item
      )))
      setNodeStatus(previous => {
        const nodeEntries = [...(previous[nodeId] || [])]
        const lastIndex = nodeEntries.length - 1
        if (lastIndex >= 0) {
          nodeEntries[lastIndex] = {
            ...nodeEntries[lastIndex],
            status: entry.status,
            error_detail: entry.error_detail
          }
        }
        return {
          ...previous,
          [nodeId]: nodeEntries
        }
      })

      if (entry.status !== 'success' && index < retryEntries.length - 1) {
        if (!setActiveFlowState(runToken, 'error', [nodeId], 'error')) return
      }
    }

    setActiveFlowState(
      runToken,
      result?.success === false ? 'error' : agentId,
      result?.success === false ? [nodeId] : [],
      result?.success === false ? 'error' : agentId
    )
  }

  const finishNodeRun = (nodeId, result) => {
    setNodeStatus(previous => ({
      ...previous,
      [nodeId]: [{
        ...(previous[nodeId]?.[0] || {}),
        status: result?.success === false ? 'error' : 'success',
        error_detail: result?.error
      }]
    }))
  }

  const handleGeneratePlan = async () => {
    if (isPlanning || isGenerating || isProcessingData || isProcessingInteractions) {
      return
    }

    // Clear previous generated content
    setDataResult(null)
    setNodeDataFlow(null)
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
    if (flowBusyRef.current || isPlanning || isGenerating || isProcessingData || isProcessingInteractions) {
      return
    }
    flowBusyRef.current = true
    const runToken = startFlowRun()

    // Clear all previously generated content
    setDataResult(null)
    setVisSpec(null)
    setNodeTableData(null)
    setNodeCode(null)
    setShowCode(false)
    setSelectedGraphNode(null)
    setAgentTrace(null)
    setActiveNodes([])
    setNodeStatus({})
    setErrorRetryEntries([])

    // Clear backend processing artifacts (keep plan)
    try { await resetProcessing(projectId) } catch (_) {}
    if (!isCurrentFlowRun(runToken)) return

    setIsGenerating(true)
    setError(null)
    setActiveAgent('plan')

    // Step 1: Generate plan if needed
    let planData = planResult
    if (!planData) {
      try {
        const result = await generatePlan(projectId)
        if (!isCurrentFlowRun(runToken)) return
        setPlanResult(result)
        planData = result
        if (result.goal && project.goal !== result.goal) {
          setProject(prev => ({ ...prev, goal: result.goal }))
          setEditGoal(result.goal)
        }
      } catch (err) {
        if (isCurrentFlowRun(runToken)) {
          setError(`Plan generation failed: ${err.message}`)
          setIsGenerating(false)
          setActiveAgent(null)
          flowBusyRef.current = false
        }
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
        startNodeRun(nodeId, getDependencyInput(nodeId, planData?.dependencies), `${nodeId}.csv`)
        const result = await processSingleDNode(projectId, nodeId)
        if (!isCurrentFlowRun(runToken)) return
        finishNodeRun(nodeId, result)
        await handleNodeErrorFlow(nodeId, result, 'data', runToken)
        if (!isCurrentFlowRun(runToken)) return
        allProcessedNodes[nodeId] = result
        loadDataFlow()
      }

      // Step 3: Process V nodes one by one
      if (vNodes.length > 0) {
        setActiveAgent('vis')
        for (const nodeId of vNodes) {
          setActiveNodes([nodeId])
          startNodeRun(nodeId, getDependencyInput(nodeId, planData?.dependencies), `${nodeId}.json`)
          const result = await processSingleVNode(projectId, nodeId)
          if (!isCurrentFlowRun(runToken)) return
          finishNodeRun(nodeId, result)
          await handleNodeErrorFlow(nodeId, result, 'vis', runToken)
          if (!isCurrentFlowRun(runToken)) return
          allProcessedNodes[nodeId] = result
          loadDataFlow()
        }
      }

      // Load accumulated result
      const result = await getDataResult(projectId)
      if (!isCurrentFlowRun(runToken)) return
      setDataResult(result)

      // Step 4: Process interactions (if I nodes exist)
      const iNodes = planData?.nodes?.I
      if (iNodes && iNodes.length > 0) {
        setActiveAgent('interaction')
        setActiveNodes(iNodes.map(n => n.id))
        try {
          const interactionResult = await processInteractions(projectId)
          if (!isCurrentFlowRun(runToken)) return
          setInteractionResults(interactionResult.interaction_results || {})
          setViewDataUrls(interactionResult.view_data_urls || {})
          const updated = await getDataResult(projectId)
          if (!isCurrentFlowRun(runToken)) return
          setDataResult(updated)
          loadDataFlow()
        } catch (interr) {
          console.warn('Interaction processing failed:', interr.message)
        }
      }
    } catch (err) {
      if (isCurrentFlowRun(runToken)) {
        setError(`Data processing failed: ${err.message}`)
      }
    } finally {
      if (isCurrentFlowRun(runToken)) {
        loadDataFlow()
        setActiveAgent(null)
        setActiveNodes([])
        setIsProcessingData(false)
        setIsGenerating(false)
        flowBusyRef.current = false
        loadAgentTrace()
      }
    }
  }

  const handleProcessData = async () => {
    if (flowBusyRef.current || isPlanning || isGenerating || isProcessingData || isProcessingInteractions) {
      return
    }
    flowBusyRef.current = true
    const runToken = startFlowRun()

    // Clear previously generated data results
    setDataResult(null)
    setVisSpec(null)
    setNodeTableData(null)
    setNodeCode(null)
    setShowCode(false)
    setSelectedGraphNode(null)
    setAgentTrace(null)
    setActiveNodes([])
    setNodeStatus({})
    setErrorRetryEntries([])

    // Clear backend processing artifacts (keep plan)
    try { await resetProcessing(projectId) } catch (_) {}
    if (!isCurrentFlowRun(runToken)) return

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
        startNodeRun(nodeId, getDependencyInput(nodeId, planResult?.dependencies), `${nodeId}.csv`)
        const result = await processSingleDNode(projectId, nodeId)
        if (!isCurrentFlowRun(runToken)) return
        finishNodeRun(nodeId, result)
        await handleNodeErrorFlow(nodeId, result, 'data', runToken)
        if (!isCurrentFlowRun(runToken)) return
        loadDataFlow()
      }

      if (vNodes.length > 0) {
        setActiveAgent('vis')
        for (const nodeId of vNodes) {
          setActiveNodes([nodeId])
          startNodeRun(nodeId, getDependencyInput(nodeId, planResult?.dependencies), `${nodeId}.json`)
          const result = await processSingleVNode(projectId, nodeId)
          if (!isCurrentFlowRun(runToken)) return
          finishNodeRun(nodeId, result)
          await handleNodeErrorFlow(nodeId, result, 'vis', runToken)
          if (!isCurrentFlowRun(runToken)) return
          loadDataFlow()
        }
      }

      const result = await getDataResult(projectId)
      if (!isCurrentFlowRun(runToken)) return
      setDataResult(result)

      const iNodes = planResult?.nodes?.I
      if (iNodes && iNodes.length > 0) {
        setActiveAgent('interaction')
        setActiveNodes(iNodes.map(n => n.id))
        try {
          const interactionResult = await processInteractions(projectId)
          if (!isCurrentFlowRun(runToken)) return
          setInteractionResults(interactionResult.interaction_results || {})
          setViewDataUrls(interactionResult.view_data_urls || {})
          const updated = await getDataResult(projectId)
          if (!isCurrentFlowRun(runToken)) return
          setDataResult(updated)
          loadDataFlow()
        } catch (interr) {
          console.warn('Interaction processing failed:', interr.message)
        }
      }
    } catch (err) {
      if (isCurrentFlowRun(runToken)) {
        setError(`Failed to process data: ${err.message}`)
      }
    } finally {
      if (isCurrentFlowRun(runToken)) {
        loadDataFlow()
        setActiveAgent(null)
        setActiveNodes([])
        setIsProcessingData(false)
        flowBusyRef.current = false
        loadAgentTrace()
      }
    }
  }

  const loadDataFlow = async () => {
    try {
      const flow = await getDataFlow(projectId)
      setNodeDataFlow(flow)
    } catch (_) {}
  }

  const handleProcessInteractions = async () => {
    if (isPlanning || isGenerating || isProcessingData || isProcessingInteractions) return

    setIsProcessingInteractions(true)
    setError(null)
    setActiveAgent('interaction')
    setActiveNodes((planResult?.nodes?.I || []).map(node => node.id))
    try {
      const result = await processInteractions(projectId)
      setInteractionResults(result.interaction_results || {})
      setViewDataUrls(result.view_data_urls || {})
      const updated = await getDataResult(projectId)
      setDataResult(updated)
      await loadDataFlow()
      await loadAgentTrace()
    } catch (err) {
      setError(`Interaction processing failed: ${err.message}`)
    } finally {
      setIsProcessingInteractions(false)
      setActiveAgent(null)
      setActiveNodes([])
    }
  }

  const handleNodeSelect = async (node) => {
    if (isPlanning || isGenerating || isProcessingData || isProcessingInteractions) {
      return
    }

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

  const hasPlan = Boolean(planResult?.nodes)
  const isBusy = isPlanning || isGenerating || isProcessingData || isProcessingInteractions

  return (
    <div className="project-detail-container">
      <div className="project-detail-header">
        <button className="back-button" onClick={() => navigate('/')}>
          ← Back
        </button>
        <h1>{project.name}</h1>
      </div>

      {error && <div className="error-message">{error}</div>}

      <div className="project-layout">
        <aside className="project-sidebar">
          <div className="sidebar-section">
            <div className="sidebar-section-title">Project Goal</div>
            {isEditing ? (
              <div className="edit-form">
                <div className="form-group">
                  <input
                    value={editName}
                    onChange={event => setEditName(event.target.value)}
                    placeholder="Project name"
                  />
                </div>
                <div className="form-group">
                  <textarea
                    value={editGoal}
                    onChange={event => setEditGoal(event.target.value)}
                    placeholder="Project goal / description"
                    rows={4}
                  />
                </div>
                <div className="edit-actions">
                  <button className="cancel-button" onClick={handleCancel}>Cancel</button>
                  <button className="save-button" onClick={handleSave}>Save</button>
                </div>
              </div>
            ) : (
              <div className="sidebar-goal-display" onClick={() => setIsEditing(true)} title="Click to edit">
                <p>{project.goal || 'No goal set. Click to edit.'}</p>
              </div>
            )}
          </div>

          <div className="sidebar-section sidebar-db-section">
            <DatabaseSection
              databases={databases}
              expandedDb={expandedDb}
              isUploading={isUploading}
              onUpload={handleFileUpload}
              onDelete={handleDeleteDatabase}
              onToggleExpand={toggleDbExpand}
              fileInputRef={fileInputRef}
            />
          </div>

          {hasPlan && (
            <RefinedRequirements requirements={planResult.refined_requirements} />
          )}

          <div className="sidebar-actions">
            <button
              className="sidebar-button plan-button"
              onClick={handleGeneratePlan}
              disabled={isBusy || databases.length === 0}
            >
              {isPlanning ? (
                <><span className="sidebar-button-spinner" /> Planning...</>
              ) : (
                'Generate Plan'
              )}
            </button>
            <button
              className="sidebar-button generate-button"
              onClick={handleGenerate}
              disabled={isBusy || !hasPlan || !planResult.nodes?.D?.length}
            >
              {isGenerating || isProcessingData ? (
                <><span className="sidebar-button-spinner" /> Generating...</>
              ) : (
                'Generate'
              )}
            </button>
            <button
              className="sidebar-button fix-button"
              onClick={() => setIsFixing(!isFixing)}
              disabled={isBusy || !hasPlan}
            >
              {isFixing ? 'Fix Mode On' : 'Fix'}
            </button>
          </div>
        </aside>

        <main className="project-main">
          {!hasPlan ? (
            <div className="plan-empty">
              <p>No plan generated yet. Upload a database and click "Generate Plan".</p>
            </div>
          ) : (
            <>
              <div className="main-section">
                <div className="main-section-header">
                  <h3>Nodes Overview</h3>
                  <button className="toggle-button" onClick={() => setShowNodes(!showNodes)}>
                    {showNodes ? 'Hide' : 'Show'} Nodes
                  </button>
                </div>
                {showNodes && (
                  <div className="nodes-grid-compact">
                    <NodeGroup label={NODE_TYPE_LABELS.d} type="d" nodes={planResult.nodes.d} />
                    <NodeGroup label={NODE_TYPE_LABELS.D} type="D" nodes={planResult.nodes.D} />
                    <NodeGroup label={NODE_TYPE_LABELS.V} type="V" nodes={planResult.nodes.V} />
                    <NodeGroup label={NODE_TYPE_LABELS.I} type="I" nodes={planResult.nodes.I} />
                  </div>
                )}
              </div>

              <div className="main-section">
                <AgentFlow
                  agents={agentTrace?.agents || null}
                  connections={agentTrace?.connections || null}
                  activeAgent={activeAgent}
                  activeNodes={activeNodes}
                  nodeStatus={nodeStatus}
                  expandedAgent={expandedAgent}
                  onToggleExpand={id => setExpandedAgent(expandedAgent === id ? null : id)}
                  generating={isBusy}
                  planNodes={planResult.nodes}
                  dependencies={planResult.dependencies}
                  errorRetryEntries={errorRetryEntries}
                />
              </div>

              {planResult.dependencies?.length > 0 && (
                <div className="main-section">
                  <div className="graph-section-header">
                    <h3>Dependency Graph</h3>
                    <button
                      className="primary-button"
                      onClick={handleGenerate}
                      disabled={isBusy || !planResult.nodes?.D?.length}
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
                    disabled={isBusy}
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

                  <DataFlowTable nodeDataFlow={nodeDataFlow} planNodes={planResult.nodes} />
                </div>
              )}

              <div className="main-section">
                <div className="main-section-header">
                  <h3>All Views</h3>
                  <div className="main-section-actions">
                    {dataResult?.processed_vis && Object.keys(dataResult.processed_vis).length > 0 && (
                      <button
                        className="primary-button"
                        onClick={handleProcessInteractions}
                        disabled={isBusy || !planResult.nodes?.I?.length}
                      >
                        {isProcessingInteractions ? 'Processing...' : 'Process Interactions'}
                      </button>
                    )}
                    <button className="toggle-button" onClick={() => setShowViews(!showViews)}>
                      {showViews ? 'Hide' : 'Show'} Views
                    </button>
                  </div>
                </div>
                {showViews && (
                  dataResult?.processed_vis && Object.keys(dataResult.processed_vis).length > 0 ? (
                    <ChartPreview
                      processedVis={dataResult.processed_vis}
                      interactionResults={interactionResults}
                      viewDataUrls={viewDataUrls}
                    />
                  ) : (
                    <div className="node-empty-box">No visualizations generated yet.</div>
                  )
                )}
              </div>
            </>
          )}
        </main>
      </div>
    </div>
  )
}

export default ProjectDetail
