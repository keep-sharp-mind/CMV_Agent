VALID_MARK_TYPES = {
    "bar", "line", "point", "area", "rect", "circle",
    "square", "text", "geoshape", "rule", "trail", "tick"
}

SYSTEM_PROMPT_CHAT_JSON = (
    "You are an expert data visualization engineer. "
    "You create clean, valid Vega-Lite specifications."
)

SYSTEM_PROMPT_GENERATE = (
    "You are an expert data visualization engineer. "
    "You create clean, valid, production-ready Vega-Lite v5 specifications."
)

VISUALIZATION_SPEC_PROMPT = """Generate a complete, valid Vega-Lite JSON specification for the following visualization task.

Target Node:
- ID: {node_id}
- Name: {node_name}
- Description: {node_description}
- Chart type hint: {chart_type}

Available Input Tables:
{inputs_json}

Stable Field Contract (empty on first generation):
{field_contract_json}

Requirements:
1. Output a JSON object with two keys: "spec" and "metadata"
2. "spec" must be a valid Vega-Lite v5 specification that can be rendered directly by vega-embed
3. Do NOT include inline "data" -> "values". Instead, add a top-level field "table": "<input_node_id>" referencing the input table that provides data for this chart (e.g. "table": "D1"). The spec must reference data by table ID, not by embedding data inline.
4. Use the chart type hint if appropriate, or choose the best mark type for the data
5. The visualization should be self-explanatory with proper axis titles, title, etc.
6. "metadata" must contain:
   - "marktype": the Vega-Lite mark type used (e.g. "bar", "line", "point", "area", "rect", "circle")
   - "used_tables": list of input table IDs that provide data for this chart
   - "used_fields": list of all field/column names referenced in the spec
   - "encoding_fields": dict mapping encoding channels (x, y, color, size, etc.) to field names
   - "input_fields_by_table": dict mapping each used input table ID to the exact fields this V spec consumes from that table. Example: {{"D1": ["team", "score"]}}
7. When the stable field contract is non-empty, preserve all required input
   fields and all required output fields used by downstream interactions.
   Do not reference undeclared input tables.
8. Use responsive sizing: set top-level `width` to `"container"` and avoid
   narrow fixed numeric widths. The chart must remain legible in a dashboard.
9. `field_profiles` contains the observed min/max and quantiles for numeric
   fields. For quantitative x/y axes, choose a domain close to the actual data
   range with modest padding. Do not force a broad zero-based range when the
   observed values occupy a narrow interval (for example, 88-97).

Output ONLY the JSON object inside ```json ... ``` blocks. Do NOT include any other text.
"""
