import { useEffect, useRef, useCallback } from 'react'
import vegaEmbed from 'vega-embed'
import viewRegistry from '../viewRegistry'

function ChartPreview({ processedVis, interactionResults, viewDataUrls }) {
  const containerRef = useRef(null)
  const viewRefs = useRef({})
  const initedRef = useRef(false)

  const initCharts = useCallback(async () => {
    if (!processedVis || Object.keys(processedVis).length === 0) return
    initedRef.current = true

    const container = containerRef.current
    if (!container) return
    container.innerHTML = ''

    // Build interaction-to-source mapping
    const iSignalSlots = {}
    const targetVIds = new Set()
    if (interactionResults) {
      Object.values(interactionResults).forEach(ir => {
        const s = ir.interaction_spec || {}
        Object.entries(ir.signal_slots || {}).forEach(([vid, sig]) => {
          if (!iSignalSlots[vid]) iSignalSlots[vid] = []
          iSignalSlots[vid].push({ iid: s.interaction_id, signal: sig })
        })
        ;(ir.target_v_ids || []).forEach(vid => targetVIds.add(vid))
      })
    }

    // Create grid
    const grid = document.createElement('div')
    grid.className = 'chart-grid'
    grid.style.cssText = 'display:grid;grid-template-columns:repeat(auto-fill,minmax(420px,1fr));gap:16px;padding:16px 0'
    container.appendChild(grid)

    for (const [vId, visData] of Object.entries(processedVis)) {
      const spec = visData.spec
      if (!spec) continue

      const card = document.createElement('div')
      card.className = 'chart-card'
      card.style.cssText = 'border:1px solid #e0e0e0;border-radius:8px;overflow:hidden;background:#fff'

      const header = document.createElement('div')
      header.style.cssText = 'padding:8px 12px;font-size:13px;font-weight:600;border-bottom:1px solid #eee;background:#fafafa'
      header.textContent = vId + ' - ' + (visData.metadata?.marktype || spec.mark || 'chart')
      card.appendChild(header)

      const chartDiv = document.createElement('div')
      chartDiv.style.cssText = 'padding:12px;min-height:300px'
      chartDiv.id = `chart-${vId}`
      card.appendChild(chartDiv)

      // Hidden data bridge for target charts
      const bridgeDiv = document.createElement('div')
      bridgeDiv.style.cssText = 'display:none'
      bridgeDiv.id = `bridge-${vId}`
      card.appendChild(bridgeDiv)

      grid.appendChild(card)

      try {
        const embedOpts = { actions: false, renderer: 'canvas', tooltip: true }
        const result = await vegaEmbed(`#chart-${vId}`, spec, embedOpts)
        const view = result.view
        viewRefs.current[vId] = view
        viewRegistry.set(vId, view)

        // Signal listeners for source charts
        const slots = iSignalSlots[vId] || []
        slots.forEach(({ iid, signal }) => {
          view.addSignalListener(signal, (name, value) => {
            window['I_Data_' + iid + '_' + vId] = value
            window.dispatchEvent(new CustomEvent('interaction-' + iid))
          })
        })

        // Data bridge for target charts: load full data from CSV URL
        if (targetVIds.has(vId)) {
          const dataUrl = (viewDataUrls || {})[vId]
          if (dataUrl) {
            const bridgeDataName = 'raw_' + vId
            const bridgeSpec = {
              $schema: spec.$schema || 'https://vega.github.io/schema/vega-lite/v5.json',
              data: { name: bridgeDataName, url: dataUrl },
              mark: { type: 'circle', size: 1, opacity: 0 },
              encoding: { x: { value: 0 }, y: { value: 0 } }
            }
            try {
              const bridgeResult = await vegaEmbed(`#bridge-${vId}`, bridgeSpec, embedOpts)
              const bv = bridgeResult.view
              await bv.runAsync()
              const fullData = bv.data(bridgeDataName) || []
              viewRegistry.set(vId + '_data', { fullData, bridgeView: bv })
            } catch (e) {
              console.warn('Data bridge failed for', vId, e)
              viewRegistry.set(vId + '_data', { fullData: [] })
            }
          } else {
            viewRegistry.set(vId + '_data', { fullData: [] })
          }
        }
      } catch (err) {
        console.error('Chart embed failed for', vId, err)
        const fb = document.createElement('div')
        fb.style.cssText = 'padding:24px;color:#999;text-align:center'
        fb.textContent = 'Failed to render ' + vId
        chartDiv.appendChild(fb)
      }
    }

    // Inject interaction JS
    if (interactionResults) {
      Object.values(interactionResults).forEach(ir => {
        if (ir.js_code) {
          try {
            const s = document.createElement('script')
            s.textContent = ir.js_code
            document.body.appendChild(s)
          } catch (e) {
            console.warn('Interaction JS injection failed:', e)
          }
        }
      })
    }
  }, [processedVis, interactionResults, viewDataUrls])

  useEffect(() => {
    initedRef.current = false
  }, [processedVis])

  useEffect(() => {
    if (!initedRef.current) {
      initCharts()
    }
    return () => {
      Object.values(viewRefs.current).forEach(v => {
        try { v.finalize() } catch (e) { /* ignore */ }
      })
      viewRefs.current = {}
      viewRegistry.clear()
      document.querySelectorAll('script').forEach(s => {
        if (s.textContent && s.textContent.includes('(function(){var IID=')) {
          s.remove()
        }
      })
    }
  }, [initCharts])

  if (!processedVis || Object.keys(processedVis).length === 0) {
    return <div className="empty-state">No visualizations to display</div>
  }

  return (
    <div className="chart-preview-container">
      <div ref={containerRef} />
    </div>
  )
}

export default ChartPreview
