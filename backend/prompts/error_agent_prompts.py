"""
Error Agent Prompts - Detailed prompts for diagnosing and fixing errors
during data processing, visualization generation, and interaction setup.
Each prompt includes the full context needed for the LLM to produce accurate
diagnoses and fixes, with explicit output schemas.
"""

# =========================================================================
# 1. VISUALIZATION ERROR ANALYSIS
# =========================================================================

VIS_ERROR_ANALYSIS_PROMPT = """You are a Vega-Lite visualization expert. Diagnose errors in a generated chart spec and suggest fixes.

## V Node Info
{node_details}

## Chart Type (from plan)
{chart_type}

## Upstream Data Tables Info
Columns available from each upstream table:
{input_tables_info}

## Vega-Lite Spec Generated
```json
{spec_json}
```

## Validation / Execution Errors
{error_details}

## Task
Analyze why the visualization spec failed. Follow this diagnostic checklist:

### Step 1 — Check data field existence
- Does every field referenced in `encoding` exist in the upstream tables?
- Are there typos in field names (e.g., "sepal_lenth" instead of "sepal_length")?
- If fields are missing, the root cause is `data_fields`.

### Step 2 — Check encoding structure
- Are required channels present? (x and y for bar/line/point, theta and radius for arc, etc.)
- Is the `mark` type valid and compatible with the encoding?
- Are aggregate functions used correctly with appropriate data types?
- If encoding or mark is wrong, the root cause is `vis_spec`.

### Step 3 — Check chart_type alignment
- Does the actual mark in the spec match the `chart_type` from the plan?
  (e.g., plan says "bar chart" but spec uses "area" mark)
- If the plan's chart_type is fundamentally wrong for the data/question, root cause is `plan_config`.
- If the plan asks for a chart type that doesn't match the node description, also flag `plan_config`.

### Step 4 — Check upstream data
- Could the D node have failed to produce the correct columns?
- Are there type mismatches (e.g., trying to aggregate a string field as if it were numeric)?
- If the upstream D node didn't produce needed data, root cause is `data_processing`.
- If the chart needs a field that no upstream output currently contains, explicitly decide whether to modify this V node, modify the upstream D node, or modify the requirement/plan.
- During regeneration, do not force a V node to preserve every previous input field. Only preserve fields that downstream I nodes actually require.

### Step 5 — JSON syntax
- Is the spec valid JSON? Any missing commas, brackets, quotes?
- Are Vega-Lite keywords misspelled? (e.g., "aggreagte" instead of "aggregate")

## Output Format
Output ONLY valid JSON with NO additional explanation outside the JSON:

Suggested fixes must be operationally specific. Do NOT write generic advice such as
"fix the spec", "repair the failing expression", "use the traceback", "check the data",
or "modify the code". Every non-null suggested fix must name the concrete field,
encoding channel, mark, aggregate, upstream node, or plan property to change.

```json
{{
  "root_cause": "vis_spec" | "data_fields" | "plan_config" | "data_processing",
  "fix_strategy": "modify_vis" | "modify_data" | "modify_plan" | "modify_data_and_vis",
  "repair_scope": ["current_node" | "upstream_node" | "requirement_or_plan"],
  "suggested_fixes": {{
    "plan_modifications": null | "specific plan field to change, e.g. change V2.chart_type from line to bar because x=`category`, y=`count`",
    "upstream_node_modifications": null | "specific upstream D/V node and exact field it must expose, e.g. D1 must output `county_fips` for V2",
    "data_modifications": null | "specific upstream data change, including node id and exact columns/derived fields",
    "vis_modifications": null | "specific Vega-Lite edits, including exact field names, mark type, encoding channel, aggregate/type changes"
  }},
  "explanation": "Concise reasoning for the diagnosis, referencing specific error messages and spec elements"
}}
```
"""


# =========================================================================
# 2. FIX VISUALIZATION SPEC
# =========================================================================

FIX_VIS_SPEC_PROMPT = """You are a Vega-Lite expert. Fix the visualization spec based on the diagnosis below.

## V Node
{node_details}

## Chart Type
{chart_type}

## Upstream Data Info
Each input table with its exact columns:
{input_tables_info}

## Previous Failed Spec
```json
{spec_json}
```

## Error Details
{error_details}

## Diagnosis & Fix Suggestion
{diagnosis_text}

## Task
Generate a corrected Vega-Lite spec. Follow these rules strictly:

1. **Field names must be exact**: Only use fields listed in the upstream data info above. Check spelling carefully.
2. **Valid Vega-Lite v5 syntax**: Use only documented properties from the Vega-Lite specification.
3. **Minimal transforms**: Avoid `transform` unless absolutely necessary for binning, filtering, or calculating.
4. **Mark compatibility**: Ensure the mark type supports the encoding channels used (e.g., don't put `theta` on a bar chart).
5. **Simple over complex**: Prefer straightforward, working charts. A simple bar/line/point chart that renders is better than a complex layered chart that fails.
6. **Include only the spec** — do not add extra properties outside the standard Vega-Lite schema.

Output a JSON object with keys "spec" and "metadata". The metadata must include:
- `marktype`: string, the mark type used
- `used_tables`: array of table IDs used
- `used_fields`: array of all field names referenced in the spec
- `encoding_fields`: object mapping channel names to field names, e.g. {{"x": "species", "y": "count"}}

```json
{{
  "spec": {{ /* Vega-Lite spec */ }},
  "metadata": {{
    "marktype": "...",
    "used_tables": ["..."],
    "used_fields": ["..."],
    "encoding_fields": {{"x": "...", "y": "..."}}
  }}
}}
```
"""


# =========================================================================
# 3. INTERACTION ERROR ANALYSIS
# =========================================================================

INTERACTION_ERROR_ANALYSIS_PROMPT = """You are an expert in Vega-Lite interactions. Diagnose errors in an interaction setup and suggest fixes.

## Interaction Node
{node_details}

## Source Views (trigger charts)
These charts initiate the interaction when the user selects/brushes:
{source_views_info}

## Target Views (affected charts)
These charts respond to the interaction:
{target_views_info}

## Interaction Spec
{interaction_spec_json}

## Generated JS Code (injected at runtime)
{js_code}

## Source View Specs (after selection param modification)
{source_specs_json}

## Target View Specs (after dual-layer restructuring)
{target_specs_json}

## Error Details
{error_details}

## Diagnostic Checklist

### Check 1 — Link field alignment
- Does the `link_field` in each source view exist as an encoding field in that source View spec?
- Does each target view's `field` exist as an encoding field in that target View spec?
- Are the source link_field and target field actually the same data concept?
- Do their `semantic` labels match the field semantic catalog, even when physical field names differ?
- If fields don't match, root cause is `data_fields`.

### Check 2 — View ID consistency
- Do all source view IDs match actual V nodes in the project?
- Do all target view IDs match actual V nodes?
- Is a V node listed as both source AND target for the same I node? (that's illegal)
- Root cause: `plan_config` if IDs are wrong.

### Check 3 — Selection parameter compatibility
- Does the source V spec support the selection type (point vs interval)?
- For interval: does the spec have at least one continuous (quantitative/temporal) axis?
- For point: does the spec have a discrete (nominal/ordinal) field to select on?
- Root cause: `vis_spec` if the source spec is incompatible.

### Check 4 — Dual-layer target restructuring
- Are the target specs correctly restructured into bg (full data, dimmed) + fg (filtered, highlighted) layers?
- Are the named datasets (`bg_{IID}_{VID}`, `fg_{IID}_{VID}`) referenced correctly in both the spec and JS code?
- Root cause: `spec_modification` if restructuring is wrong.

### Check 5 — JS code logic
- Does the JS code correctly read the selection signal from window variable `I_Data_{{IID}}_{{VID}}`?
- Does it correctly extract link_field values for point selections?
- Does it correctly handle interval brush ranges?
- Does it correctly set bg/fg datasets and call runAsync?
- Root cause: `interaction_code` if JS logic is flawed.

## Output Format
Provide a detailed diagnosis and fix suggestions. Output ONLY valid JSON:

Suggested fixes must be operationally specific. Do NOT write generic advice such as
"fix interaction", "fix JS", "repair code", "check link fields", or "update the spec".
Every non-null suggested fix must name the concrete source/target view id, link_field,
selection signal/window variable, dataset name, Vega-Lite channel, or JS expression to change.

```json
{{
  "root_cause": "interaction_code" | "vis_spec" | "plan_config" | "data_fields" | "spec_modification",
  "fix_strategy": "modify_interaction" | "modify_vis" | "modify_plan" | "modify_data",
  "repair_scope": ["current_node" | "upstream_node" | "requirement_or_plan"],
  "suggested_fixes": {{
    "plan_modifications": null | "specific I-node trigger/effect/dependency change, naming source and target view ids",
    "upstream_node_modifications": null | "specific upstream V/D node and exact field it should expose",
    "requirement_modifications": null | "specific infeasible interaction requirement to revise/remove and why",
    "data_modifications": null | "specific missing link field or derived field to add, with upstream node id",
    "vis_modifications": [] | [{{"v_id": "V1", "fix_hint": "specific Vega-Lite/channel/data field edit"}}, ...],
    "interaction_modifications": "specific JS/spec edits, including exact variable names such as I_Data_<IID>_<VID>, bg_<IID>_<VID>, fg_<IID>_<VID>, link_field, and filtering logic"
  }},
  "explanation": "Concise reasoning referencing specific error messages and spec elements"
}}
```
"""


# =========================================================================
# 4. FIX INTERACTION
# =========================================================================

FIX_INTERACTION_PROMPT = """You are a Vega-Lite interaction expert. Fix the interaction setup based on the diagnosis below.

## Interaction Node
{node_details}

## Source Views (trigger charts)
{source_views_info}

## Target Views (affected charts)
{target_views_info}

## Previous Failed Interaction Spec
{interaction_spec_json}

## Previous Generated JS Code
```javascript
{js_code}
```

## Error Details
{error_details}

## Diagnosis & Fix Suggestion
{diagnosis_text}

## Available Fields per View
{available_fields}

## Task
Generate a corrected interaction spec that fixes the issues identified in the diagnosis.

### Rules for the Interaction Spec
1. `source_views` array: each item has `id`, `select`, `source_channels`, `link_field`, and canonical `semantic`
2. `controlled_view` array: each item has `view`, `field`, `action`, and canonical `semantic`
3. Source `link_field` and target `field` may have different names, but must exist in their respective specs and have the same canonical `semantic`
4. All view IDs and field names must match the actual specs

### Rules for JS Code
- The JS code must read window variable `I_Data_{{IID}}_{{VID}}` for each source view
- Store selected values by `semantic`, then apply them to each target's own physical `field`; do not assume source and target field names are identical
- For point selections: extract link_field values from the selected objects
- For interval selections: read the range from source_channels[0] (e.g., raw["x"] gives [min, max])
- Set `bg_{{IID}}_{{VID}}` and `fg_{{IID}}_{{VID}}` datasets on each target view
- Use `viewRegistry.get(viewId + '_data').fullData` for the full dataset
- Call `viewRegistry.get(viewId).runAsync()` after updating data

Output a JSON object:

```json
{{
  "interaction_spec": {{
    "source_views": [{{"id": "V4", "select": "interval", "source_channels": ["x"], "link_field": "source_species", "semantic": "species"}}],
    "controlled_view": [{{"view": "V1", "field": "target_species", "action": "filter", "semantic": "species"}}]
  }},
  "js_fix_hint": "Description of what changed in the JS logic compared to the previous version"
}}
```
"""


# =========================================================================
# 5. DATA PROCESSING ERROR ANALYSIS
# =========================================================================

DATA_ERROR_ANALYSIS_PROMPT = """You are a senior Python/pandas incident diagnostician. Diagnose the failed data-processing code using the exact runtime evidence below.

## D Node Info
{node_details}

## Input Tables
Exact profiles of each upstream input (path variable, columns, dtypes, null counts, and sample rows):
{input_tables_info}

## Generated Python Code
```python
{code}
```

## Execution Errors
{error_details}

## Diagnostic Checklist

### Step 1 — Column existence
- Does every column name used in the code exist in the input tables?
- Are there typos in column names?
- Are case differences causing mismatches?

### Step 2 — Data type compatibility
- Are there operations that mix incompatible types (e.g., string + int)?
- Are aggregation functions appropriate for the column type?
- Are groupby fields categorical (not numeric)?

### Step 3 — Syntax & runtime errors
- Does the code have Python syntax errors?
- Are there NameErrors for undefined variables?
- Are there pandas API misuses (e.g., wrong method name)?

### Step 4 — Logical correctness
- Is the merge/join on the correct columns?
- Is the grouping correct for the intended aggregation?
- Are the results saved in the expected format?

### Step 5 — Runtime evidence and output contract
- Use the traceback to identify the failing expression and exception type; do not guess when evidence is available.
- Every input must be read through its provided `INPUT_TABLE_PATH_*` variable.
- The final value must be a non-empty pandas DataFrame assigned to `result_df`.
- Treat NaN/Inf validation failures as errors that require an explicit, task-appropriate cleanup strategy.
- Never suggest fabricated sample data, hardcoded file paths, swallowing exceptions, or disabling validation.

## Output Format
Output ONLY valid JSON:

Suggested fixes must be operationally specific. Do NOT write generic advice such as
"repair the failing expression", "use the traceback", "fix the code", "check columns",
or "handle the error". Every non-null suggested fix must name exact column names,
input node ids, pandas operations, variables, or output fields. If the exact replacement
field is uncertain, list the closest available candidates and say which upstream node
or requirement should change if none is semantically valid.

```json
{{
  "root_cause": "missing_input" | "column_name" | "data_type" | "syntax_error" | "runtime_error" | "empty_result" | "invalid_values" | "logic_error" | "output_contract",
  "fix_strategy": "modify_code" | "modify_data_selection" | "modify_upstream" | "modify_requirement",
  "repair_scope": ["current_node" | "upstream_node" | "requirement_or_plan"],
  "suggested_fixes": {{
    "code_modifications": "specific pandas/code edits, naming exact failing expression, columns, variables, and required result_df/# INPUT_FIELDS updates",
    "upstream_node_modifications": null | "specific upstream D node and exact output fields it should produce",
    "requirement_modifications": null | "specific requirement to revise/remove if the requested field cannot be produced",
    "data_modifications": null | "specific upstream data/field change needed, naming node id and columns"
  }},
  "evidence": ["Exact error/traceback/column evidence supporting the diagnosis"],
  "explanation": "Concise reasoning for the diagnosis"
}}
```
"""


# =========================================================================
# 6. FIX DATA PROCESSING CODE
# =========================================================================

FIX_DATA_CODE_PROMPT = """You are a senior Python/pandas engineer. Repair the failed data-processing code based on the diagnosis and exact runtime evidence below.

## D Node
{node_details}

## Input Table Profiles
{input_tables_info}

## Previous Failed Code
```python
{code}
```

## Error Details
{error_details}

## Diagnosis & Fix Suggestion
{diagnosis_text}

## Task
Generate corrected Python code. Rules:
1. The first line MUST be `# INPUT_FIELDS: {{...}}`, a valid JSON object mapping every consumed input node ID to the exact fields the repaired code uses.
2. Use ONLY the column names listed in the input tables above — check spelling and case exactly.
3. The final result must be saved to the variable `result_df` as a pandas DataFrame. This name is mandatory.
4. Read inputs only with `pd.read_csv(INPUT_TABLE_PATH_...)` using the provided variables; never use a literal or invented path.
5. Preserve the node's intended task. Do not replace the real transformation with fabricated data or a no-op unless the task explicitly requires it.
6. Fix the precise failing expression identified by the traceback and diagnosis.
7. Handle missing values, numeric conversion, merge keys, empty groups, and division-by-zero explicitly when relevant.
8. Do not catch broad exceptions merely to hide failures. Do not write files, print output, install packages, access the network, or call `exit()`.
9. Return one JSON object containing executable code and metadata.
10. During regeneration, preserve downstream-required output fields, not every previous input field. Input fields may change if the repaired node still produces the required outputs correctly.
11. If the required output cannot be produced from available inputs, do not fabricate it; the diagnosis should recommend modifying an upstream node or the requirement/plan.

```json
{{
  "code": "# INPUT_FIELDS: {{\\\"D1\\\": [\\\"field_a\\\"]}}\\nimport pandas as pd\\n...\\nresult_df = ...",
  "metadata": {{
    "used_tables": ["D1"],
    "used_fields": ["species", "sepal_length"],
    "output_columns": ["species", "sepal_length", "count"]
  }}
}}
```
"""


# =========================================================================
# 7. PLAN ERROR ANALYSIS
# =========================================================================

ANALYZE_PLAN_ERRORS_PROMPT = """You are a data analysis plan expert. Diagnose validation errors in a plan's dependency graph.

## Analysis Requirements
{requirements_text}

## Current Node Definitions
{node_details}

## Current Dependencies
{current_dependencies_json}

## Validation Errors Found
{error_details}

## Dependency Graph Rules (the plan FAILED these rules)
{validation_rules_text}

## Diagnostic Checklist

### Check 1 — Graph connectivity
- Does every non-d node (D, V, I) have at least one valid incoming predecessor edge?
- Are there orphaned nodes that no edge connects to?
- Are d-nodes (input tables) the only nodes without incoming edges?
- Can every D/V/I node be traced backward through predecessors to a lowercase d source?

### Check 2 — Edge types
- Every D needs at least one incoming d->D or D->D edge (data source).
- Every V needs exactly ONE incoming d->V or D->V edge (data for visualization).
- Every I needs at least one incoming V->I edge (trigger source).
- Every I needs at least one outgoing I->V edge (affected target).

### Check 3 — I-node rules
- An I node must have BOTH: at least one V->I incoming AND at least one I->V outgoing.
- The same V cannot be both trigger source AND affected target for one I node.
- I nodes cannot connect to other I nodes, D nodes, or d nodes.

### Check 4 — Cycles
- The graph MUST be acyclic. Any cycle needs one edge removed or redirected.

### Check 5 — Node purpose
- Does every D node have at least one downstream consumer (via D->D or D->V)?
- Are there nodes that exist but don't connect to the goal/requirements?

### Check 6 — Requirement alignment
- Do the requirements justify all existing nodes?
- Are there requirements that can't be satisfied by any node?
- Could a node be removed if its corresponding requirement is removed or merged?

### Check 7 — Data feasibility
- Does any D/V node request a metric explicitly marked as unavailable or not provided?
- Is a count, frequency, identifier, or constant being relabeled as performance/effectiveness/quality?
- Data-feasibility failures are requirement errors, not edge errors: set `root_cause` to `requirements` and `needs_requirement_change` to true.

## Output Format
Output ONLY valid JSON:

```json
{{
  "root_cause": "dependency_graph" | "requirements",
  "suggestions": "Detailed natural language description of what needs to change and why — including specific node IDs, edge types, and structural changes",
  "affected_nodes": ["D3", "V2"],
  "needs_requirement_change": false,
  "explanation": "Brief reasoning for the diagnosis, referencing specific error messages"
}}
```
"""


# =========================================================================
# 6. FIX DEPENDENCIES
# =========================================================================

FIX_DEPENDENCIES_PROMPT = """You are a data analysis plan expert. Fix the dependency graph based on the analysis below.

## Analysis Requirements
{requirements_text}

## Current Node Definitions
{node_details}

## Validation Errors
{error_details}

## Diagnosis
{diagnosis_text}

## Dependency Type Rules (ALLOWED types ONLY)
1. d -> D: D reads from input table d
2. D -> D: D depends on another D's output
3. d -> V: V uses raw input table data directly
4. D -> V: V uses processed data from a D node
5. V -> I: I is triggered from chart V (trigger source)
6. I -> V: I affects chart V (affected target, DIFFERENT from trigger source)

## CRITICAL I Node Rules
- I nodes have ONLY incoming V->I edges and ONLY outgoing I->V edges
- V<->I BIDIRECTIONAL is ILLEGAL
- The same V CANNOT be both trigger source AND affected target for one I node
- I nodes CANNOT connect to other I nodes

## Dependency Graph Validation Rules (ALL must be satisfied)
1. Every D/V/I node must have at least one valid incoming predecessor; only d nodes may have none
2. Every D must have at least one incoming d->D or D->D edge
3. Every V must have exactly ONE incoming d->V or D->V data edge
4. Every I must have an incoming V->I and an outgoing I->V to a different V
5. The graph MUST be acyclic (no cycles like D1->D2->D1)
6. Every edge endpoint must exist and edge type must match the endpoint node types
7. Duplicate edges, self-loops, incoming edges to d, D->I, I->D, V->D, and I->I are forbidden
8. Every D node should be connected to at least one downstream consumer (D->D or D->V)

## Task
Output ONLY the corrected `dependencies` array. Add or remove edges as needed. Do NOT modify nodes — only fix the edges.

```json
[
  {{"from": "...", "to": "...", "type": "..."}},
  ...
]
```
"""


# =========================================================================
# 7. FIX REQUIREMENTS
# =========================================================================

FIX_REQUIREMENTS_PROMPT = """You are a data analysis plan expert. Fix the refined requirements based on the analysis below.

## Overall Goal
{goal}

## Current Refined Requirements
{current_requirements_json}

## Current Node Definitions
{node_details}

## Validation Errors
{error_details}

## Diagnosis
{diagnosis_text}

## Task
The validation errors indicate that some requirements lead to problematic nodes (e.g., orphaned nodes, nodes with no useful purpose). Fix the requirements by:
- Removing or merging redundant requirements that produce useless nodes
- Adjusting requirement descriptions so they lead to well-connected nodes
- Do NOT add new requirements unless absolutely necessary
- Keep the total number of requirements between 2-6
- Each requirement id should follow the pattern "R1", "R2", etc.

Output the corrected requirements as a JSON array. Each requirement has:

```json
[
  {{
    "id": "R1",
    "name": "Requirement name",
    "description": "Brief description of what this requirement analyzes and why it needs data processing and visualization"
  }}
]
```
"""
