import ValueRange from './ValueRange'

function NodeDetailSection({
  node,
  nodeTableData,
  isLoadingNodeData,
  dataResult,
  visSpec,
  showCode,
  nodeCode,
  isLoadingNodeCode,
  onToggleCode,
  showVisCode,
  onToggleVisCode,
  chartContainerRef,
  dataFlow,
  interactionSpec,
  showInteractionCode,
  onToggleInteractionCode
}) {
  if (!node) return null

  const isD = node.type === 'd' || node.type === 'D'
  const isV = node.type === 'V'
  const isI = node.type === 'I'
  const processedInfo = dataResult?.processed_nodes?.[node.id]
  const hasProcessed = processedInfo?.success
  const columns = isD ? (nodeTableData?.columns || processedInfo?.columns || []) : []
  const rowCount = nodeTableData?.row_count ?? processedInfo?.row_count

  const renderDContent = () => {
    if (isLoadingNodeData) {
      return <div className="loading" style={{ padding: '24px', textAlign: 'center' }}>Loading table data...</div>
    }

    if (!hasProcessed && !processedInfo && columns.length === 0) {
      return <div className="node-empty-box">Click "Generate" to process this node</div>
    }

    return (
      <>
        <div className="node-meta-bar">
          <code>{node.id}.csv</code>
          {rowCount != null && columns.length > 0 && (
            <span className="node-meta-counts">{rowCount} rows · {columns.length} cols</span>
          )}
        </div>

        {columns.length > 0 && (
          <div className="node-columns-box">
            {columns.map(col => (
              <div key={col.column_name} className="node-col-row">
                <span className="node-col-name">{col.column_name}</span>
                <span className="node-col-type">{col.data_type}</span>
                {col.is_nullable && <span className="nullable-badge">nullable</span>}
                {col.value_range && <ValueRange valueRange={col.value_range} dataType={col.data_type} />}
              </div>
            ))}
          </div>
        )}

        {processedInfo && !hasProcessed && (
          <div className="node-error-box">
            <strong>{node.id} failed:</strong>
            {processedInfo.error && <div className="node-error-line">{processedInfo.error}</div>}
            {processedInfo.syntax_check?.error && (
              <div className="node-error-line">Syntax: {processedInfo.syntax_check.error}</div>
            )}
            {processedInfo.validation_issues?.map((i, idx) => (
              <div key={idx} className="node-error-line">Validation: {i.detail}</div>
            ))}
          </div>
        )}

        {showCode && nodeCode && (
          <div className="code-box">
            <pre><code>{nodeCode}</code></pre>
          </div>
        )}
      </>
    )
  }

  const renderIContent = () => {
    if (!interactionSpec) {
      return <div className="node-empty-box">No interaction result available. Process interactions first.</div>
    }

    const ispec = interactionSpec.interaction_spec || {}
    const srcViews = ispec.source_views || []
    const ctrlViews = ispec.controlled_view || []
    const jsCode = interactionSpec.js_code || ''

    return (
      <>
        <div className="node-vis-info">
          {srcViews.length > 0 && (
            <div className="node-vis-tag"><strong>Source Views:</strong> {srcViews.map(s => `${s.id} (${s.select}, ch:${(s.source_channels||[]).join(',')}, link:${s.link_field})`).join('; ')}</div>
          )}
          {ctrlViews.length > 0 && (
            <div className="node-vis-tag"><strong>Controlled Views:</strong> {ctrlViews.map(c => `${c.view} (field:${c.field}, ${c.action})`).join('; ')}</div>
          )}
        </div>

        {interactionSpec.recovered && (
          <div className="node-vis-tag" style={{color:'#d97706',marginTop:'8px'}}><strong>⚠ Recovered from error</strong></div>
        )}

        {showInteractionCode && jsCode && (
          <div className="code-box" style={{marginTop:'8px'}}>
            <pre><code>{jsCode}</code></pre>
          </div>
        )}
      </>
    )
  }

  const renderVContent = () => {
    if (!visSpec) {
      return <div className="node-empty-box">No visualization generated. Click "Generate".</div>
    }

    const metadata = visSpec.metadata || {}
    const spec = visSpec.spec || {}

    const specEncodings = (() => {
      if (!spec || !spec.encoding) return null
      return Object.entries(spec.encoding).map(([channel, enc]) => ({
        channel,
        field: enc.field || enc.fieldName || '?',
        type: enc.type || '',
        aggregate: enc.aggregate || ''
      }))
    })()

    return (
      <>
        <div className="node-vis-info">
          <div className="node-vis-tag"><strong>Mark:</strong> {metadata.marktype || spec.mark || 'N/A'}</div>
          {metadata.used_tables?.length > 0 && (
            <div className="node-vis-tag"><strong>Data:</strong> {metadata.used_tables.join(', ')}</div>
          )}
          {metadata.used_fields?.length > 0 && (
            <div className="node-vis-tag"><strong>Fields:</strong> {metadata.used_fields.join(', ')}</div>
          )}
        </div>

        {specEncodings && specEncodings.length > 0 && (
          <div className="node-encoding-box">
            {specEncodings.map((enc, i) => (
              <div key={i} className="node-enc-row">
                <span className="node-enc-channel">{enc.channel}</span>
                <span className="node-enc-arrow">→</span>
                <span className="node-enc-field">{enc.field}</span>
                <span className="node-enc-type">({enc.type}{enc.aggregate ? `, ${enc.aggregate}` : ''})</span>
              </div>
            ))}
          </div>
        )}

        {visSpec.spec && (
          <div className="chart-wrapper" ref={chartContainerRef}></div>
        )}

        {!visSpec.success && visSpec.error && (
          <div className="node-error-box">Validation: {visSpec.error}</div>
        )}

        {visSpec.validation_issues?.length > 0 && (
          <div className="node-validation-box">
            {visSpec.validation_issues.map((issue, i) => (
              <div key={i}>{issue.type}: {issue.detail}</div>
            ))}
          </div>
        )}

        {showVisCode && visSpec?.spec_json && (
          <div className="code-box">
            <pre><code>{visSpec.spec_json}</code></pre>
          </div>
        )}
      </>
    )
  }

  return (
    <div className="node-detail-container">
      <div className="node-detail-header">
        <span className={`node-type-badge ${node.type}-badge`}>{node.type}</span>
        <span className="node-detail-id">{node.id}</span>
        <span className="node-detail-sep">-</span>
        <span className="node-detail-name">{node.name}</span>
        <div className="node-detail-header-right">
          {isD && hasProcessed && (
            <button className="code-btn" onClick={onToggleCode} disabled={isLoadingNodeCode}>
              {isLoadingNodeCode ? 'Loading...' : showCode ? 'Hide Code' : 'Show Code'}
            </button>
          )}
          {isV && visSpec?.spec_json && (
            <button className="code-btn" onClick={onToggleVisCode}>
              {showVisCode ? 'Hide Code' : 'Show Code'}
            </button>
          )}
          {isI && interactionSpec?.js_code && (
            <button className="code-btn" onClick={onToggleInteractionCode}>
              {showInteractionCode ? 'Hide JS' : 'Show JS'}
            </button>
          )}
        </div>
      </div>

      {node.description && <p className="node-desc-text">{node.description}</p>}
      {isD && node.task && <div className="node-task-line"><strong>Task:</strong> {node.task}</div>}

      {isD && renderDContent()}
      {isV && renderVContent()}
      {isI && renderIContent()}

      {dataFlow && (
        <div className="node-data-flow">
          <div className="node-data-flow-header">Data Flow</div>
          <div className="node-data-flow-body">
            {dataFlow.in_fields?.length > 0 || dataFlow.predicted_in_fields?.length > 0 ? (
              <div className="node-data-flow-col">
                <strong>In Fields</strong>
                <div className="node-data-flow-tags">
                  {dataFlow.in_fields?.map((f, i) => (
                    <span key={i} className="data-flow-tag in">{f}</span>
                  ))}
                  {dataFlow.predicted_in_fields?.map((f, i) => (
                    <span key={`pin-${i}`} className="data-flow-tag predicted" title="Predicted shared-field fallback">{f}</span>
                  ))}
                </div>
              </div>
            ) : (
              <div className="node-data-flow-col">
                <strong>In Fields</strong>
                <div className="node-data-flow-tags"><span className="data-flow-tag in" style={{opacity:0.5}}>—</span></div>
              </div>
            )}
            {dataFlow.out_fields?.length > 0 || dataFlow.predicted_out_fields?.length > 0 ? (
              <div className="node-data-flow-col">
                <strong>Out Fields</strong>
                <div className="node-data-flow-tags">
                  {dataFlow.out_fields?.map((f, i) => (
                    <span key={i} className="data-flow-tag out">{f}</span>
                  ))}
                  {dataFlow.predicted_out_fields?.map((f, i) => (
                    <span key={`pout-${i}`} className="data-flow-tag predicted" title="Predicted shared-field fallback">{f}</span>
                  ))}
                </div>
              </div>
            ) : (
              <div className="node-data-flow-col">
                <strong>Out Fields</strong>
                <div className="node-data-flow-tags"><span className="data-flow-tag out" style={{opacity:0.5}}>—</span></div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

export default NodeDetailSection
