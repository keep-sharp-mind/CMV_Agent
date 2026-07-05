SYSTEM_PROMPT_CHAT_JSON = (
    "You are an expert data engineer. "
    "You write clean, correct Python code using pandas for data processing."
)

SYSTEM_PROMPT_GENERATE = (
    "You are an expert data engineer. "
    "You write clean, correct, production-ready Python code using pandas."
)

PROCESSING_CODE_PROMPT = """Generate Python code using pandas to perform the following data processing task.

Target Node:
- ID: {node_id}
- Name: {node_name}
- Description: {node_description}
- Task: {node_task}

Pre-defined Path Variables (these Python variables are set in the execution environment — use them directly in pd.read_csv()):
{path_variables}

Input Table Details (columns, data types, sample rows for reference):
{inputs_json}

Stable Field Contract (empty on first generation):
{field_contract_json}

Requirements:
1. The first line MUST be a machine-readable comment declaring the exact input fields consumed from each input node:
   `# INPUT_FIELDS: {{"d1": ["field_a", "field_b"], "D1": ["field_c"]}}`
   Use actual input node IDs as keys. Include only fields read or used by this node, not output-only/renamed fields.
2. Read each input table using pd.read_csv(VARIABLE_NAME) where VARIABLE_NAME is one of the pre-defined path variables listed above
3. DO NOT use string literals like 'path_to_your_file.csv', 'data.csv', 'input.csv', or any hardcoded filenames — always reference the pre-defined variable
4. DO NOT create sample data with pd.DataFrame(...) — always read from the actual CSV files using the provided path variables
5. Perform the data processing task described above
6. The final result must be stored in a variable named 'result_df' (a pandas DataFrame)
7. Do NOT include any print statements or plt.show() calls
8. Do NOT write to any files - the result will be saved by the caller
9. Handle missing values appropriately
10. Make sure column names are clean and meaningful
11. Use English for all variable names and comments
12. When the stable field contract is non-empty, preserve every required input
    and required output field exactly. Do not read undeclared predecessors.
13. Never fabricate an unavailable analytical metric or use a convenient proxy
    merely because the requested field is absent. In particular, do not rename
    row counts, identifiers, or frequencies as performance/effectiveness/quality.
    Let execution validation fail rather than producing a misleading result.

Example pattern:
```python
# INPUT_FIELDS: {{"D1": ["field_a", "field_b"]}}
import pandas as pd
df_input = pd.read_csv(INPUT_TABLE_PATH_D1)
# ... processing ...
result_df = df_input
```

Output ONLY the Python code inside ```python ... ``` blocks.
"""


FIELD_SEMANTICS_PROMPT = """Infer canonical semantics for the fields produced by a completed pandas data-processing node.

## D Node
- ID: {node_id}
- Name: {node_name}
- Description: {node_description}
- Task: {node_task}

## Generated Code
```python
{code}
```

## Previously Known Field Semantics
This catalog contains all raw and previously generated tables:
{previous_semantics_json}

## New Output Table
{output_profile_json}

## Rules
1. Return one entry for every output field and no nonexistent fields.
2. `concept` is a canonical, entity-independent semantic label in lower_snake_case.
   Fields such as `argentina_formation`, `brazil_formation`, `team_a_formation`, and `team_b_formation` should all use the concept `formation`.
3. Preserve entity/team identity separately in `entity_scope`; do not encode it into `concept`.
4. Distinguish genuinely different meanings even when names are similar.
5. Use the code, task, source lineage, values, and previous semantics together. Do not infer from the field name alone.
6. `semantic_type` must be one of: categorical, quantitative, temporal, identifier, boolean, text, unknown.
7. `source_fields` lists the upstream fields that semantically contribute to the output.
8. Output only valid JSON.

```json
{{
  "fields": {{
    "output_field": {{
      "concept": "canonical_concept",
      "entity_scope": "team/entity name or null",
      "description": "Precise meaning of this field",
      "semantic_type": "categorical",
      "unit": null,
      "source_fields": [
        {{"node_id": "d1", "field": "source_field"}}
      ],
      "confidence": 0.95
    }}
  }}
}}
```
"""
